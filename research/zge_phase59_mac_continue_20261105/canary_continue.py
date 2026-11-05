"""Real sample-only replay continuation with an explicit 12D posterior update.

The original input model and training data remain immutable. This is not a
new-date increment or PIT certification; sample cross-sectional ranks are only
defined on the 2500-row engineering sample.
"""
from __future__ import annotations
import __future__,ast,hashlib,json,pickle,time
from pathlib import Path
import numpy as np
import pandas as pd
import runtime as r

SAMPLE=r.MODEL/'sample_all_a_panel_2500.parquet';FEATURES=r.MODEL/'feature_order_v3_1.json';CUTOFF=20261008
STRUCT=['kb_personal_vol_quantile_z','J','kb_personal_j_quantile_z','kb_white_yellow_bowl_score','digested_big_green_rebuild_flag',
 'undigested_big_green_veto_flag','day1_high_j_pullback_flag','jcb_accumulation_intensity','tactic_pb1_shallow_white_score',
 'tactic_pb2_yellow_bowl_b1_score','tactic_pb3_keyk_low_spring_score','tactic_b2_yang_confirm_score','mkt_ew_ret_5d','p53_jcb_rs_5d_excess']

def weights_function():
    source=r.source('P5_9_TRANSFER_ADAPTIVE_ENGINE');tree=ast.parse(source.read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='compute_sample_weights_scheme']
    if len(nodes)!=1:raise ValueError('WEIGHT_SOURCE_FUNCTION_MISSING')
    for n in ast.walk(nodes[0]):
        if isinstance(n,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal)):raise ValueError('UNSAFE_WEIGHT_FUNCTION')
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('open','eval','exec','compile','__import__'):raise ValueError('UNSAFE_WEIGHT_CALL')
    module=ast.Module(body=nodes,type_ignores=[]);ast.fix_missing_locations(module);scope={'np':np,'pd':pd}
    exec(compile(module,str(source),'exec',flags=__future__.annotations.compiler_flag,dont_inherit=True),scope)
    return scope['compute_sample_weights_scheme']

def arrhash(a):return hashlib.sha256(np.asarray(a,dtype='<f8').tobytes()).hexdigest()
def write_json(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def maturity_mask(df,cutoff):
    signal=pd.to_numeric(df.signal_date,errors='coerce');end=pd.to_numeric(df.exit_date_t5,errors='coerce')
    signal_ok=pd.to_datetime(signal.astype('Int64').astype('string'),format='%Y%m%d',errors='coerce').notna()
    end_ok=pd.to_datetime(end.astype('Int64').astype('string'),format='%Y%m%d',errors='coerce').notna()
    candidate=signal_ok&end_ok&signal.le(cutoff)&end.le(cutoff)&df.status_t5.eq('MATURED')
    if (candidate&end.lt(signal)).any():raise ValueError('LABEL_DATE_BEFORE_SIGNAL')
    return candidate

def main():
    t=time.time();r.install_compat()
    if r.sha(SAMPLE)!='7139943f56ed6bc934b9c96b04d772bbe33648efa108f8f4e4fb56bddeac3b95':raise ValueError('SAMPLE_HASH_DRIFT')
    features=json.loads(FEATURES.read_text());assert r.sha(FEATURES)=='6d4e8f60a7854f1895976e1d462975d4645fc0dc01d2b92661d8111b28172325' and len(features)==87
    df=pd.read_parquet(SAMPLE);assert len(df)==2500 and not df.duplicated(['ts_code','signal_date']).any()
    if not df.ts_code.astype(str).str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():raise ValueError('SAMPLE_MARKET_OR_CODE_INVALID')
    required=set(features+STRUCT+['ts_code','signal_date','exit_date_t5','status_t5','ret_t5_pct','domain_source','gap_trading_days','zge_buypoint_type'])
    if required-set(df.columns):raise ValueError('MISSING_REQUIRED_COLUMNS:'+str(sorted(required-set(df.columns))))
    df=df.copy()
    for c in set(features+STRUCT+['signal_date','exit_date_t5','ret_t5_pct','gap_trading_days']):df[c]=pd.to_numeric(df[c],errors='coerce')
    mature=maturity_mask(df,CUTOFF)
    known_target=np.isfinite(df.ret_t5_pct)&np.isfinite(df.p54_repr_ridge_projected_score)
    domain_known=df.domain_source.notna();is_background=df.domain_source.eq('UNIVERSE_B_DAILY_NO_SIGNAL_PANEL')
    # Missing gap/type on a triggered event cannot silently become source defaults.
    weight_known=domain_known&(is_background|(np.isfinite(df.gap_trading_days)&df.zge_buypoint_type.notna()))
    eligible=mature&known_target&weight_known;fit=df.loc[eligible].copy().reset_index(drop=True)
    if len(fit)<30:raise ValueError('INSUFFICIENT_CANARY_MATURED_ROWS:'+str(len(fit)))
    rank=fit.groupby('signal_date')['ret_t5_pct'].rank(pct=True)-.5
    y=.70*rank.to_numpy(dtype='float64')+.30*fit.p54_repr_ridge_projected_score.to_numpy(dtype='float64')
    w=weights_function()(fit,'W6_STRATIFIED_HYBRID_WEIGHT')
    if not (np.isfinite(y).all() and np.isfinite(w).all() and (w>0).all()):raise ValueError('NONFINITE_TARGET_OR_WEIGHT')
    name='model_t5_v3_1_all_a.pkl';model=r.load(r.MODEL/name,r.MODEL_SHA[name])
    if model.feat_cols!=features or model.n_random_effects!=12:raise ValueError('MODEL_IDENTITY_MISMATCH')
    before={'ridge_coef':model.ridge_.coef_.copy(),'rff_coef':model.rff_.coef_.copy(),'trees':len(model.gbdt_.trees_),
        'prep_median':model.prep_.medians_.copy(),'prep_mean':model.prep_.means_.copy(),'prep_std':model.prep_.stds_.copy()}
    n_before=len(model.stock_posteriors_);X=model.prep_.transform(fit)
    # Keep the saved preprocessor fixed: changing its coordinates without
    # transforming old Ridge/RFF parameters would change the existing model.
    model.ridge_.continue_fit(X,y,lr=.004,epochs=6)
    model.rff_.continue_fit(X,y,lr=.004,epochs=4)
    model.gbdt_.continue_fit(X,y,n_extra_trees=10,sample_weight=w)
    pred_backbone=model.predict_backbone(fit);residual=y-pred_backbone
    valid_struct=np.isfinite(fit[STRUCT].to_numpy(dtype='float64')).all(axis=1)
    known_stock=fit.ts_code.astype(str).isin(model.stock_posteriors_).to_numpy()
    posterior_mask=valid_struct&known_stock
    z=model.build_structural_design_matrix_12d(fit.loc[posterior_mask].reset_index(drop=True));res=residual[posterior_mask]
    sub=fit.loc[posterior_mask].reset_index(drop=True)
    if len(sub)==0:raise ValueError('NO_COMPLETE_12D_MATURED_POSTERIOR_ROWS')
    updates=[]
    for symbol,idx in sub.groupby('ts_code',sort=True).indices.items():
        old=model.stock_posteriors_[str(symbol)];old_alpha=float(old['alpha_post']);old_beta=np.asarray(old['beta_post'],dtype='float64').copy()
        if old_beta.shape!=(12,) or not np.isfinite(old_beta).all():raise ValueError('INVALID_PRIOR_12D:'+str(symbol))
        n=len(idx);bars=int(old.get('total_bars',0));low_mult=.25 if bars<60 else (.60 if n<6 else 1.)
        lam=n/(n+model.tau_intercept)*low_mult
        alpha=float(np.clip(lam*float(np.mean(res[idx]))+(1-lam)*old_alpha,-.025,.025))
        tau=model.tau_slope/max(.15,low_mult);Z=z[idx];new_beta=np.linalg.solve(Z.T@Z+tau*np.eye(12),Z.T@(res[idx]-alpha)+tau*old_beta)
        new_beta[3]=np.clip(new_beta[3],.002,.032);new_beta[4]=np.clip(new_beta[4],-.048,-.010);new_beta[5]=np.clip(new_beta[5],-.038,-.006);new_beta=np.clip(new_beta,-.048,.038)
        old['alpha_post']=alpha;old['beta_post']=new_beta;old['dominant_tactics']=model._classify_dominant_tactic(new_beta)
        # The batch may replay old events. Do not relabel these as new unique history.
        old['continuation_replay_rows']=n;old['continuation_cutoff']=CUTOFF;old['continuation_unique_history_certified']=False
        row={'ts_code':str(symbol),'rows':n,'alpha_before':old_alpha,'alpha_after':alpha,'prior_n_matured_fit_preserved':int(old['n_matured_fit'])}
        for j in range(12):row[f'beta{j:02d}_before']=float(old_beta[j]);row[f'beta{j:02d}_after']=float(new_beta[j]);row[f'beta{j:02d}_delta']=float(new_beta[j]-old_beta[j])
        updates.append(row)
    model._build_fast_lookup_tables();assert len(model.stock_posteriors_)==n_before
    dest=r.OUT/'canary_v1';dest.mkdir(exist_ok=False)
    fit['sample_target_rank']=rank.to_numpy(dtype='float64');fit['sample_target_blend']=y;fit['sample_w6_weight']=w
    fit['posterior_eligible_12d']=posterior_mask;fit.to_parquet(dest/'fit_rows.parquet',index=False,compression='zstd')
    pd.DataFrame(updates).to_parquet(dest/'posterior_before_after.parquet',index=False,compression='zstd')
    output=dest/'model_t5_sample_replay.pkl'
    with output.open('xb') as f:pickle.dump(model,f,protocol=4)
    scores=model.predict(df);base=pd.read_parquet(r.OUT/'baseline_compat.parquet');assert np.isfinite(scores).all() and len(scores)==len(base)
    predicted=base[['sample_row_id','ts_code','signal_date','score_t5']].copy();predicted=predicted.rename(columns={'score_t5':'baseline_score_t5'});predicted['continued_score_t5']=scores
    predicted.to_parquet(dest/'same_sample_predictions.parquet',index=False,compression='zstd')
    upd=pd.DataFrame(updates);diffs={f'beta{j:02d}':{'recomputed_stocks':len(upd),'changed_stocks':int((upd[f'beta{j:02d}_delta'].abs()>1e-15).sum())} for j in range(12)}
    delta={'ridge_coef_l2':float(np.linalg.norm(model.ridge_.coef_-before['ridge_coef'])),'rff_coef_l2':float(np.linalg.norm(model.rff_.coef_-before['rff_coef'])),
        'gbdt_trees_before':before['trees'],'gbdt_trees_after':len(model.gbdt_.trees_),
        'prep_median_unchanged':np.array_equal(model.prep_.medians_,before['prep_median']),
        'prep_mean_unchanged':np.array_equal(model.prep_.means_,before['prep_mean']),'prep_std_unchanged':np.array_equal(model.prep_.stds_,before['prep_std'])}
    if not (delta['ridge_coef_l2']>0 and delta['rff_coef_l2']>0 and delta['gbdt_trees_after']>delta['gbdt_trees_before']):raise ValueError('NO_BACKBONE_CHANGE')
    if not any(v['changed_stocks']>0 for v in diffs.values()):raise ValueError('NO_PERSONAL_POSTERIOR_CHANGE')
    receipt={'status':'SAMPLE_REPLAY_FIT_COMPLETE_FRESH_PROCESS_PENDING','scope':'2500_ROW_ENGINEERING_CANARY_NOT_FULL_CONTINUATION','cutoff':CUTOFF,
      'sample_rows':len(df),'sample_symbols':int(df.ts_code.nunique()),'matured_cutoff_rows':int(mature.sum()),'known_target_rows':int((mature&known_target).sum()),
      'eligible_fit_rows':len(fit),'eligible_fit_stocks':int(fit.ts_code.nunique()),'posterior_complete_rows':int(posterior_mask.sum()),
      'posterior_updated_stocks':len(updates),'unknown_structural_rows':int((~valid_struct).sum()),'unknown_stock_rows':int((~known_stock).sum()),
      'unknown_weight_rows_among_matured_targets':int((mature&known_target&~weight_known).sum()),
      'fit_signal_date_min':int(fit.signal_date.min()),'fit_signal_date_max':int(fit.signal_date.max()),'fit_exit_date_max':int(fit.exit_date_t5.max()),
      'label_maturity_rule':'status_t5=MATURED AND signal_date<=cutoff AND exit_date_t5<=cutoff; prior data PIT unverified',
      'target':'0.70*(sample-only cross-sectional ret_t5 rank-0.5)+0.30*provided p54 ridge projection',
      'feature_missing_nonfinite_cells':int((~np.isfinite(fit[features].to_numpy(dtype=float))).sum()),
      'weight_rule':'pinned source W6; ridge/RFF source continue_fit unweighted; GBDT weighted',
      'posterior_rule':'old stock posterior as regularized mean; source tau/low-sample/clips; full 12D solve on matured structurally complete rows; no covariance proof',
      'replay_warning':'CANARY may replay already-fitted rows; old n_matured_fit preserved; not a certified new-date increment',
      'parameter_delta':delta,'posterior_dimensions':diffs,'posterior_stock_count_before_after':[n_before,len(model.stock_posteriors_)],
      'original_model_sha256':r.MODEL_SHA[name],'continued_model_path':str(output),'continued_model_sha256':r.sha(output),
      'fit_rows_sha256':r.sha(dest/'fit_rows.parquet'),'posterior_before_after_sha256':r.sha(dest/'posterior_before_after.parquet'),
      'same_sample_predictions_sha256':r.sha(dest/'same_sample_predictions.parquet'),'baseline_sha256':r.sha(r.OUT/'baseline_compat.parquet'),
      'runtime_seconds':round(time.time()-t,3),'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'research_only':True}
    write_json(dest/'FIT_RECEIPT.json',receipt);print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()
