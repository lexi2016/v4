"""MATURED_HARD_TARGET_CONTINUATION on the pinned, masked 303161-row source.

This is an exposed-history research replay, not new-date training, clean PIT,
or a strategy test. Model preprocessing remains frozen. Posterior update is
an explicitly distinct, direct structural-rank objective, not the cloud
backbone-residual posterior. Unknown structural z11 is an unobserved masked
contribution, never asserted as an observed zero.
"""
import json,os,pickle,resource,sys,time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from threadpoolctl import threadpool_limits,threadpool_info
import runtime as r
from canary_continue import STRUCT,weights_function,maturity_mask,arrhash

ROOT=r.OUT;DATA=ROOT/'inputs/HARD_CANDIDATE_87.parquet';PROV=ROOT/'inputs/HARD_CANDIDATE_PROVENANCE.parquet'
OUT=ROOT/'full_hard_replay_v1'; CUTOFF=20261015
DATA_SHA='ced3e88415ed31a061e86d3f1a03fc136c0b476a4fca9eb7a8614845efae9bb3'
PROV_SHA='bed4ca766f327257676d9c4a27378c0a869584341f0a8edf049d7ea2298f05fd'
MODEL='model_t5_v3_1_all_a.pkl';P54=None

def dumpj(p,obj):
    t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n');os.replace(t,p)
def snap(stage,t0,cpu0,**kw):
    rss=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    rec={'stage':stage,'wall_seconds':round(time.time()-t0,3),'cpu_seconds':round(time.process_time()-cpu0,3),'peak_rss_bytes':rss,
         'threads_env':{k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS')},**kw}
    dumpj(OUT/'CHECKPOINT_STATUS.json',rec);print(json.dumps(rec,ensure_ascii=False),flush=True)
    if rss>48*1024**3:raise MemoryError('RSS_BUDGET_EXCEEDED_STOP')
def save_model(model,name):
    p=OUT/name
    with p.open('xb') as f:pickle.dump(model,f,protocol=4);f.flush();os.fsync(f.fileno())
    return p

def metrics(score,ret):
    ok=np.isfinite(score)&np.isfinite(ret);s=score[ok];z=ret[ok];yp=z>0;n1=int(yp.sum());n0=len(yp)-n1
    auc=None if not n0 or not n1 else float((rankdata(s)[yp].sum()-n1*(n1+1)/2)/(n0*n1))
    sr=rankdata(s);rr=rankdata(z);std=float(sr.std()*rr.std());sp=None if std==0 else float(np.mean((sr-sr.mean())*(rr-rr.mean()))/std)
    return {'rows':len(s),'positive_return_rows':n1,'auc_direction':auc,'spearman_raw_return':sp,
            'scope':'IN_SAMPLE_EXPOSED_REPLAY; UNCALIBRATED; NOT_HOLDOUT_OR_TRADING'}

def main():
    t0=time.time();c0=time.process_time();OUT.mkdir(exist_ok=False);r.install_compat()
    if r.sha(DATA)!=DATA_SHA or r.sha(PROV)!=PROV_SHA:raise ValueError('PINNED_INPUT_HASH_MISMATCH')
    df=pd.read_parquet(DATA);prov=pd.read_parquet(PROV);features=json.loads((r.MODEL/'feature_order_v3_1.json').read_text())
    if len(df)!=303161 or len(prov)!=len(df) or df.duplicated(['ts_code','signal_date']).any():raise ValueError('KEY_OR_ROW_INVALID')
    if not df[['ts_code','signal_date']].equals(prov[['ts_code','signal_date']]):raise ValueError('PROVENANCE_KEYS_MISALIGNED')
    p54=[c for c in features if c.startswith('p54_repr_')];assert len(p54)==11 and df[p54].isna().all().all()
    for c in set(features+STRUCT+['signal_date','exit_date_t5','ret_t5_pct','gap_trading_days']):df[c]=pd.to_numeric(df[c],errors='coerce')
    mature=maturity_mask(df,CUTOFF);valid_ret=np.isfinite(df.ret_t5_pct)
    malformed=df.status_t5.eq('MATURED')&(pd.to_numeric(df.exit_date_t5,errors='coerce').lt(df.signal_date)|df.exit_date_t5.isna())
    if malformed.any():raise ValueError('MALFORMED_MATURE_T5_LABEL')
    rank=pd.Series(np.nan,index=df.index,dtype=float);rank.loc[mature&valid_ret]=df.loc[mature&valid_ret].groupby('signal_date').ret_t5_pct.rank(pct=True)-.5
    background=df.domain_source.eq('UNIVERSE_B_DAILY_NO_SIGNAL_PANEL')
    w_ok=df.domain_source.notna()&(background|(np.isfinite(df.gap_trading_days)&df.zge_buypoint_type.notna()))
    eligible=mature&valid_ret&w_ok&rank.notna();fit=df.loc[eligible].copy().reset_index(drop=True);y=rank.loc[eligible].to_numpy(float)
    w=np.asarray(weights_function()(fit,'W6_STRATIFIED_HYBRID_WEIGHT'),dtype=float)
    if len(fit)<1000 or not np.isfinite(y).all() or not np.isfinite(w).all() or not (w>0).all():raise ValueError('FIT_INPUT_INVALID')
    model=r.load(r.MODEL/MODEL,r.MODEL_SHA[MODEL]);assert model.feat_cols==features and model.n_random_effects==12
    names13=[x for x in STRUCT if x!='p53_jcb_rs_5d_excess']; assert len(names13)==13
    valid13=np.isfinite(fit[names13].to_numpy(float)).all(axis=1);known=fit.ts_code.astype(str).isin(model.stock_posteriors_).to_numpy()
    postmask=valid13&known;z11_obs=postmask&np.isfinite(fit.p53_jcb_rs_5d_excess.to_numpy(float))
    if not postmask.any() or not z11_obs.any():raise ValueError('NO_STRUCTURAL_POSTERIOR_OBSERVATIONS')
    cov={c:{'finite_fit_rows':int(np.isfinite(fit[c].to_numpy(float)).sum()),'unknown_fit_rows':int((~np.isfinite(fit[c].to_numpy(float))).sum()),
            'source':'DELIVERED_87_FEATURE_LINEAGE_PRODUCER_CLAIM','first_available':'CANNOT_CONFIRM','PIT':'CANNOT_CONFIRM'} for c in STRUCT}
    for c in p54:
        if not fit[c].isna().all():raise ValueError('TEACHER_MUST_BE_UNKNOWN')
    fitid=fit[['ts_code','signal_date','exit_date_t5','status_t5','ret_t5_pct']].copy()
    fitid['hard_rank_target']=y;fitid['source_w6_weight']=w;fitid['posterior_eligible_13_known_inputs']=postmask;fitid['posterior_z11_observed']=z11_obs
    fitid.to_parquet(OUT/'fit_rows_and_masks.parquet',index=False,compression='zstd')
    meta={'source_rows':len(df),'source_stocks':int(df.ts_code.nunique()),'mature_at_cutoff':int(mature.sum()),
          'mature_with_return':int((mature&valid_ret).sum()),'fit_rows':len(fit),'fit_stocks':int(fit.ts_code.nunique()),
          'mature_known_return_unknown_weight':int((mature&valid_ret&~w_ok).sum()),'posterior_rows':int(postmask.sum()),
          'posterior_stocks':int(fit.loc[postmask,'ts_code'].nunique()),'z11_observed_rows':int(z11_obs.sum()),
          'z11_observed_stocks':int(fit.loc[z11_obs,'ts_code'].nunique()),'structural_unknown_counts':cov,
          'cutoff':CUTOFF,'fit_signal_min':int(fit.signal_date.min()),'fit_signal_max':int(fit.signal_date.max()),
          'fit_exit_max':int(fit.exit_date_t5.max()),'positive_return_rows':int((fit.ret_t5_pct>0).sum()),
          'nonpositive_return_rows':int((fit.ret_t5_pct<=0).sum()),'negative_return_rows':int((fit.ret_t5_pct<0).sum()),
          'target':'HARD_RANK: per signal_date rank(pct, average) of ret_t5 among all matured <= cutoff minus 0.5; kappa=0',
          'posterior':'direct hard-rank response on structural 12D with exposed prior; no teacher, backbone or imputer input',
          'z11':'observation-mask: 2024 profile SOURCE-DECLARED only, others UNKNOWN; omitted coordinate has zero design contribution but is not observed zero',
          'PIT':'CANNOT_CONFIRM','fit_scope':'REPLAY_ADAPTATION_DIRECTION_ONLY'}
    dumpj(OUT/'FIT_COHORT.json',meta);snap('COHORT_BOUND',t0,c0,**{k:meta[k] for k in ('source_rows','mature_at_cutoff','fit_rows','fit_stocks','posterior_rows','posterior_stocks','z11_observed_rows')})
    # Freeze same-input exported baseline predictions BEFORE any weight update.
    with threadpool_limits(limits=8): base=model.predict(fit)
    if not np.isfinite(base).all():raise ValueError('BASELINE_PRED_NONFINITE')
    basefile=OUT/'baseline_same_fit_predictions.parquet';fitid[['ts_code','signal_date','exit_date_t5','ret_t5_pct','hard_rank_target']].assign(score=base).to_parquet(basefile,index=False,compression='zstd')
    snap('BASELINE_FROZEN',t0,c0,baseline_sha256=r.sha(basefile))
    before={'ridge':model.ridge_.coef_.copy(),'rff':model.rff_.coef_.copy(),'trees':len(model.gbdt_.trees_),
            'medians':model.prep_.medians_.copy(),'means':model.prep_.means_.copy(),'stds':model.prep_.stds_.copy()}
    with threadpool_limits(limits=1):
        X=model.prep_.transform(fit);model.ridge_.continue_fit(X,y,lr=.004,epochs=6)
    snap('RIDGE_FIT',t0,c0)
    with threadpool_limits(limits=8):model.rff_.continue_fit(X,y,lr=.004,epochs=4)
    pregbdt=save_model(model,'checkpoint_after_ridge_rff.pkl');snap('RFF_FIT_CHECKPOINT',t0,c0,checkpoint_sha256=r.sha(pregbdt))
    # Source's pure-numpy continue_fit: append 10 trees, source W6 weights.
    with threadpool_limits(limits=1):model.gbdt_.continue_fit(X,y,n_extra_trees=10,sample_weight=w)
    treecp=save_model(model,'checkpoint_after_gbdt.pkl');snap('GBDT_FIT_CHECKPOINT',t0,c0,trees=len(model.gbdt_.trees_),checkpoint_sha256=r.sha(treecp))
    # Independent structural-rank update. Setting missing z11's matrix entry
    # to zero expresses NO observation/contribution, not an observed value.
    sub=fit.loc[postmask].copy().reset_index(drop=True);z11=np.isfinite(sub.p53_jcb_rs_5d_excess.to_numpy(float));sub_for_z=sub.copy()
    sub_for_z.loc[~z11,'p53_jcb_rs_5d_excess']=0.0
    Z=model.build_structural_design_matrix_12d(sub_for_z);Z[~z11,11]=0.0;Y=y[postmask]
    if not np.isfinite(Z).all() or not np.isfinite(Y).all():raise ValueError('STRUCTURAL_OBS_INVALID')
    # Keep all fitted keys and individual source/mask; no imputer or teacher is read here.
    updates=[];groups=sub.groupby('ts_code',sort=True).indices;olds={tc:(float(v['alpha_post']),np.asarray(v['beta_post'],dtype=float).copy()) for tc,v in model.stock_posteriors_.items()}
    with threadpool_limits(limits=1):
      for tc,idx in groups.items():
        old=model.stock_posteriors_[str(tc)];old_a,old_b=olds[str(tc)];n=len(idx);obs=int(z11[idx].sum());bars=int(old.get('total_bars',0))
        low=.25 if bars<60 else (.60 if n<6 else 1.);lam=n/(n+model.tau_intercept)*low
        alpha=float(np.clip(lam*float(np.mean(Y[idx]))+(1-lam)*old_a,-.025,.025))
        tau=model.tau_slope/max(.15,low);Zi=Z[idx];beta=np.linalg.solve(Zi.T@Zi+tau*np.eye(12),Zi.T@(Y[idx]-alpha)+tau*old_b)
        beta[3]=np.clip(beta[3],.002,.032);beta[4]=np.clip(beta[4],-.048,-.010);beta[5]=np.clip(beta[5],-.038,-.006);beta=np.clip(beta,-.048,.038)
        if not obs:beta[11]=old_b[11]
        old['alpha_post']=alpha;old['beta_post']=beta;old['dominant_tactics']=model._classify_dominant_tactic(beta)
        old['continuation_replay_rows']=n;old['continuation_cutoff']=CUTOFF;old['continuation_unique_history_certified']=False
        row={'ts_code':str(tc),'rows':n,'z11_observed_rows':obs,'alpha_before':old_a,'alpha_after':alpha,'tau_slope_effective':float(tau),
             'prior_n_matured_fit_preserved':int(old['n_matured_fit'])}
        for j in range(12):row[f'beta{j:02d}_before']=float(old_b[j]);row[f'beta{j:02d}_after']=float(beta[j]);row[f'beta{j:02d}_delta']=float(beta[j]-old_b[j])
        updates.append(row)
    model._build_fast_lookup_tables();upd=pd.DataFrame(updates);upd.to_parquet(OUT/'posterior_before_after.parquet',index=False,compression='zstd')
    dim={f'beta{j:02d}':{'updated_stocks':int((upd[f'beta{j:02d}_delta'].abs()>1e-15).sum()),'total_updated_stocks':len(upd),
         'observed_rows':int(z11_obs.sum()) if j==11 else int(postmask.sum()),'observed_stocks':int((upd.z11_observed_rows>0).sum()) if j==11 else len(upd)} for j in range(12)}
    deltas={'ridge_coef_l2':float(np.linalg.norm(model.ridge_.coef_-before['ridge'])),'rff_coef_l2':float(np.linalg.norm(model.rff_.coef_-before['rff'])),
            'trees_before':before['trees'],'trees_after':len(model.gbdt_.trees_),
            'preprocessor_frozen':bool(np.array_equal(model.prep_.medians_,before['medians']) and np.array_equal(model.prep_.means_,before['means']) and np.array_equal(model.prep_.stds_,before['stds']))}
    if deltas['ridge_coef_l2']<=0 or deltas['rff_coef_l2']<=0 or deltas['trees_after']!=deltas['trees_before']+10 or not deltas['preprocessor_frozen']:raise ValueError('PARAMETER_CHANGE_CHECK_FAILED')
    final=save_model(model,'model_t5_hard_replay.pkl');snap('POSTERIOR_MODEL_SAVED',t0,c0,model_sha256=r.sha(final),posterior_stocks=len(upd),parameter_delta=deltas)
    with threadpool_limits(limits=8):cont=model.predict(fit)
    if not np.isfinite(cont).all():raise ValueError('CONTINUED_PRED_NONFINITE')
    both=fitid[['ts_code','signal_date','exit_date_t5','ret_t5_pct','hard_rank_target']].copy();both['baseline_score']=base;both['continued_score']=cont
    both.to_parquet(OUT/'same_fit_predictions.parquet',index=False,compression='zstd')
    receipt={'status':'FULL_INPUT_REPLAY_FIT_COMPLETE_FRESH_PROCESS_QA_PENDING','research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
        'objective':'MATURED_HARD_TARGET_CONTINUATION','kappa':0,'scope':'REPLAY_ADAPTATION_NOT_PIT_NOT_SEALED',
        'candidate_sha256':DATA_SHA,'provenance_sha256':PROV_SHA,'original_model_sha256':r.MODEL_SHA[MODEL],
        'parent_prior_sha256':'identical to original model sha; individual old values preserved in posterior_before_after.parquet',
        'continued_model_path':str(final),'continued_model_sha256':r.sha(final),'baseline_predictions_sha256':r.sha(basefile),
        'predictions_sha256':r.sha(OUT/'same_fit_predictions.parquet'),'fit_rows_sha256':r.sha(OUT/'fit_rows_and_masks.parquet'),
        'posterior_sha256':r.sha(OUT/'posterior_before_after.parquet'),'cohort_path':str(OUT/'FIT_COHORT.json'),
        'cohort_sha256':r.sha(OUT/'FIT_COHORT.json'),'parameter_delta':deltas,'dimensions':dim,
        'posterior_method':'DIRECT structural hard rank, regularized toward exposed original alpha/beta; beta clamps from source; not backbone residual or exact Bayesian update',
        'weight':'source W6 for GBDT; original ridge/RFF continuation unweighted',
        'comparisons':{'baseline':metrics(base,fit.ret_t5_pct.to_numpy(float)),'continued':metrics(cont,fit.ret_t5_pct.to_numpy(float))},
        'limits':['IN_SAMPLE_ALL_EXPOSED','candidate has missing masked features; frozen imputer is old exposed','old model and old prior not cleaned',
                  'first availability and PIT unverified','observed prices are direction proxy only','scores uncalibrated','not a strategy or BUY'],
        'environment':{'python':sys.executable,'numpy':np.__version__,'pandas':pd.__version__,'threadpools':threadpool_info()},
        'wall_seconds':round(time.time()-t0,3),'cpu_seconds':round(time.process_time()-c0,3),'peak_rss_bytes':int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}
    dumpj(OUT/'FIT_RECEIPT.json',receipt);snap('FIT_FINISHED',t0,c0,receipt_sha256=r.sha(OUT/'FIT_RECEIPT.json'))
if __name__=='__main__':main()
