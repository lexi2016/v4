"""Continue T5 parent on newly matured, independent local-QFQ labels.

Original cloud feature rows and labels are immutable. This is a local-source
migration research run; the same rows are used for fitting and evaluation.
"""
import json,os,pickle,resource,sys,time
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits,threadpool_info
import runtime as r
from canary_continue import STRUCT,weights_function
from fit_hard_replay import metrics

ROOT=r.OUT;RUN=ROOT/'local_increment_v1';DATA=ROOT/'inputs/HARD_CANDIDATE_87.parquet';OVER=ROOT/'inputs/LOCAL_LABEL_OVERLAY_R3.parquet'
PARENT=ROOT/'full_hard_replay_v1/model_t5_hard_replay.pkl';PARENT_SHA='63c66f90badd425dcc2607fced5b6d378856be5605beb6184204dcca64d20708'
DATA_SHA='ced3e88415ed31a061e86d3f1a03fc136c0b476a4fca9eb7a8614845efae9bb3';OVER_SHA='0c4849d3a970a328178fe8bfccc012ce6d1481ff8acda8456bcd0d0a1f8bc528'

def dumpj(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def savem(m,p):
    with p.open('xb') as f:pickle.dump(m,f,protocol=4);f.flush();os.fsync(f.fileno())
def main():
    start=time.time();cpu=time.process_time();RUN.mkdir(exist_ok=False);r.install_compat()
    if r.sha(DATA)!=DATA_SHA or r.sha(OVER)!=OVER_SHA:raise ValueError('INPUT_HASH_DRIFT')
    parent=r.load(PARENT,PARENT_SHA);features=json.loads((r.MODEL/'feature_order_v3_1.json').read_text())
    src=pd.read_parquet(DATA);over=pd.read_parquet(OVER);keys=['ts_code','signal_date']
    if len(over)!=6664 or over.duplicated(keys).any() or src.duplicated(keys).any():raise ValueError('INPUT_KEY_CONFLICT')
    if not over.cloud_original_status_t5.eq('PENDING').all():raise ValueError('ORIGINAL_PENDING_CHANGED')
    if not over.local_label_identity.eq('LOCAL_PANEL_QFQ_ASOF_20261104_OPEN_TO_OPEN_T5_V1').all():raise ValueError('LABEL_VERSION_INVALID')
    local=over[over.local_label_status.eq('KNOWN_LOCAL_LABEL')].copy()
    if not (local.local_exit_date.between(20261016,20261104).all() and local.signal_date.between(20261009,20261015).all()):raise ValueError('LOCAL_MATURITY_OR_SCOPE_INVALID')
    fields=['local_entry_open','local_exit_open','local_entry_volume','local_exit_volume']
    if not (np.isfinite(local[fields].to_numpy(float)).all() and (local[fields].to_numpy(float)>0).all()):raise ValueError('LOCAL_BAD_OPEN_VOLUME')
    if not (local.local_entry_valid.eq(True).all() and local.local_exit_valid.eq(True).all()):raise ValueError('LOCAL_OHLC_INVALID')
    if not np.allclose((local.local_exit_open/local.local_entry_open-1)*100,local.local_ret_t5_pct,rtol=0,atol=1e-12):raise ValueError('LOCAL_RETURN_MISALIGNED')
    prev=pd.read_parquet(ROOT/'full_hard_replay_v1/fit_rows_and_masks.parquet',columns=keys)
    if len(local[keys].merge(prev,on=keys,how='inner')):raise ValueError('DUPLICATE_PARENT_FIT_KEY')
    fit=local.merge(src,on=keys,how='left',validate='one_to_one',indicator=True)
    if not fit['_merge'].eq('both').all() or not fit.status_t5.eq('PENDING').all():raise ValueError('FEATURE_KEY_NOT_FOUND')
    fit=fit.drop(columns='_merge').reset_index(drop=True)
    p54=[x for x in features if x.startswith('p54_repr_')];assert len(p54)==11 and fit[p54].isna().all().all()
    assert fit.p53_jcb_rs_5d_excess.isna().all()
    background=fit.domain_source.eq('UNIVERSE_B_DAILY_NO_SIGNAL_PANEL');w_ok=fit.domain_source.notna()&(background|(pd.to_numeric(fit.gap_trading_days,errors='coerce').notna()&fit.zge_buypoint_type.notna()))
    ranks=fit.groupby('signal_date').local_ret_t5_pct.rank(pct=True)-.5
    skip=int((~w_ok).sum());fit=fit.loc[w_ok].copy().reset_index(drop=True);y=ranks.loc[w_ok].to_numpy(float)
    w=np.asarray(weights_function()(fit,'W6_STRATIFIED_HYBRID_WEIGHT'),dtype=float)
    if len(fit)<30 or not np.isfinite(y).all() or not np.isfinite(w).all() or not (w>0).all():raise ValueError('NO_VALID_INCREMENT_FIT')
    struct13=[c for c in STRUCT if c!='p53_jcb_rs_5d_excess'];valid13=np.isfinite(fit[struct13].to_numpy(float)).all(axis=1);known=fit.ts_code.astype(str).isin(parent.stock_posteriors_).to_numpy();pm=valid13&known
    if not pm.any():raise ValueError('NO_VALID_INCREMENT_POSTERIOR')
    row=fit[keys+['local_entry_date','local_exit_date','local_entry_open','local_exit_open','local_entry_volume','local_exit_volume','local_ret_t5_pct']].copy()
    row['hard_rank_target']=y;row['source_w6_weight']=w;row['posterior_eligible_13_known_inputs']=pm;row['posterior_z11_observed']=False
    row.to_parquet(RUN/'fit_rows_and_masks.parquet',index=False,compression='zstd')
    print(json.dumps({'stage':'COHORT_BOUND','source_tail_rows':len(over),'known_local_rows':len(local),'fit_rows':len(fit),'fit_stocks':int(fit.ts_code.nunique()),'posterior_rows':int(pm.sum()),'parent_overlap':0,'excluded_unknown_weight':skip},ensure_ascii=False),flush=True)
    # Parent predict, on same local rows, is saved before any fit.
    with threadpool_limits(limits=8):before_pred=parent.predict(fit)
    if not np.isfinite(before_pred).all():raise ValueError('PARENT_PRED_NONFINITE')
    row[keys+['local_ret_t5_pct','hard_rank_target']].assign(score=before_pred).to_parquet(RUN/'parent_predictions.parquet',index=False,compression='zstd')
    old={'ridge':parent.ridge_.coef_.copy(),'rff':parent.rff_.coef_.copy(),'trees':len(parent.gbdt_.trees_),'med':parent.prep_.medians_.copy(),'mean':parent.prep_.means_.copy(),'std':parent.prep_.stds_.copy()}
    with threadpool_limits(limits=1):
        X=parent.prep_.transform(fit);parent.ridge_.continue_fit(X,y,lr=.004,epochs=6)
    with threadpool_limits(limits=8):parent.rff_.continue_fit(X,y,lr=.004,epochs=4)
    savem(parent,RUN/'checkpoint_ridge_rff.pkl');print(json.dumps({'stage':'BACKBONE_CHECKPOINT','elapsed_s':round(time.time()-start,2)}),flush=True)
    with threadpool_limits(limits=1):parent.gbdt_.continue_fit(X,y,n_extra_trees=10,sample_weight=w)
    savem(parent,RUN/'checkpoint_gbdt.pkl')
    sub=fit.loc[pm].copy().reset_index(drop=True);yy=y[pm];sub['p53_jcb_rs_5d_excess']=0.0
    Z=parent.build_structural_design_matrix_12d(sub);Z[:,11]=0.0
    if not np.isfinite(Z).all():raise ValueError('STRUCTURAL_NONFINITE')
    changes=[]
    with threadpool_limits(limits=1):
      for tc,idx in sub.groupby('ts_code',sort=True).indices.items():
        obj=parent.stock_posteriors_[str(tc)];old_a=float(obj['alpha_post']);old_b=np.asarray(obj['beta_post'],dtype=float).copy();n=len(idx);bars=int(obj.get('total_bars',0))
        low=.25 if bars<60 else (.60 if n<6 else 1.);lam=n/(n+parent.tau_intercept)*low;alpha=float(np.clip(lam*float(np.mean(yy[idx]))+(1-lam)*old_a,-.025,.025));tau=parent.tau_slope/max(.15,low);z=Z[idx]
        beta=np.linalg.solve(z.T@z+tau*np.eye(12),z.T@(yy[idx]-alpha)+tau*old_b);beta[3]=np.clip(beta[3],.002,.032);beta[4]=np.clip(beta[4],-.048,-.010);beta[5]=np.clip(beta[5],-.038,-.006);beta=np.clip(beta,-.048,.038)
        beta[11]=old_b[11]  # NO z11 observations, preserve exposed prior.
        obj['alpha_post']=alpha;obj['beta_post']=beta;obj['dominant_tactics']=parent._classify_dominant_tactic(beta);obj['continuation_local_increment_rows']=n;obj['continuation_local_label_cutoff']=20261104
        change={'ts_code':str(tc),'new_matured_rows':n,'z11_observed_rows':0,'alpha_before':old_a,'alpha_after':alpha,'tau_slope_effective':float(tau),'prior_n_matured_fit_preserved':int(obj['n_matured_fit'])}
        for j in range(12):change[f'beta{j:02d}_before']=float(old_b[j]);change[f'beta{j:02d}_after']=float(beta[j]);change[f'beta{j:02d}_delta']=float(beta[j]-old_b[j])
        changes.append(change)
    parent._build_fast_lookup_tables();changes=pd.DataFrame(changes);changes.to_parquet(RUN/'posterior_before_after.parquet',index=False,compression='zstd')
    delta={'ridge_coef_l2':float(np.linalg.norm(parent.ridge_.coef_-old['ridge'])),'rff_coef_l2':float(np.linalg.norm(parent.rff_.coef_-old['rff'])),
           'gbdt_trees_before':old['trees'],'gbdt_trees_after':len(parent.gbdt_.trees_),
           'preprocessor_frozen':bool(np.array_equal(parent.prep_.medians_,old['med']) and np.array_equal(parent.prep_.means_,old['mean']) and np.array_equal(parent.prep_.stds_,old['std']))}
    if delta['ridge_coef_l2']<=0 or delta['rff_coef_l2']<=0 or delta['gbdt_trees_after']!=delta['gbdt_trees_before']+10 or not delta['preprocessor_frozen']:raise ValueError('INCREMENT_PARAMETER_DELTA_FAILED')
    model=RUN/'model_t5_local_increment.pkl';savem(parent,model)
    with threadpool_limits(limits=8):after_pred=parent.predict(fit)
    pred=row[keys+['local_ret_t5_pct','hard_rank_target']].copy();pred['parent_score']=before_pred;pred['increment_score']=after_pred;pred.to_parquet(RUN/'same_fit_predictions.parquet',index=False,compression='zstd')
    dim={f'beta{j:02d}':{'changed_stocks':int((changes[f'beta{j:02d}_delta'].abs()>1e-15).sum()),'observed_rows':0 if j==11 else int(pm.sum()),'updated_stocks':len(changes)} for j in range(12)}
    report={'status':'LOCAL_LABEL_INCREMENT_FIT_COMPLETE_FRESH_PROCESS_QA_PENDING','label_identity':'LOCAL_PANEL_QFQ_ASOF_20261104_OPEN_TO_OPEN_T5_V1',
      'scope':'NEW_LOCAL_MATURED_LABELS_ON_EXISTING_20261009_20261015_FEATURE_KEYS; CROSS_SOURCE_MIGRATION_RESEARCH','source_tail_rows':len(over),'known_local_rows':len(local),
      'fit_rows':len(fit),'fit_stocks':int(fit.ts_code.nunique()),'posterior_rows':int(pm.sum()),'posterior_stocks':len(changes),'z11_observed_rows':0,'unknown_weight_excluded':skip,
      'label_cutoff':20261104,'fit_signal_min':int(fit.signal_date.min()),'fit_signal_max':int(fit.signal_date.max()),'exit_min':int(fit.local_exit_date.min()),'exit_max':int(fit.local_exit_date.max()),
      'new_key_parent_overlap':0,'original_cloud_status_retained':'PENDING','overlay_reasons':over.local_label_status.value_counts().to_dict(),
      'objective':'same-day matured local ret_t5 rank minus 0.5, kappa=0; parent frozen preprocessor; source W6 for +10 trees',
      'posterior':'direct structural hard-rank response and parent prior; no teacher/backbone/imputer; z11 UNKNOWN and unchanged',
      'parameter_delta':delta,'dimensions':dim,'parent_model_sha256':PARENT_SHA,'candidate_sha256':DATA_SHA,'local_label_overlay_sha256':OVER_SHA,
      'local_model_path':str(model),'local_model_sha256':r.sha(model),'fit_rows_sha256':r.sha(RUN/'fit_rows_and_masks.parquet'),
      'parent_predictions_sha256':r.sha(RUN/'parent_predictions.parquet'),'same_fit_predictions_sha256':r.sha(RUN/'same_fit_predictions.parquet'),
      'posterior_sha256':r.sha(RUN/'posterior_before_after.parquet'),'comparison':{'parent':metrics(before_pred,fit.local_ret_t5_pct.to_numpy(float)),'continued':metrics(after_pred,fit.local_ret_t5_pct.to_numpy(float))},
      'limits':['same-row fit/evaluation is not holdout','local/cloud source identity differs; equivalence CANNOT_CONFIRM','teacher/feature PIT and calibration CANNOT_CONFIRM','local labels direction proxy only'],
      'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
      'environment':{'python':sys.executable,'numpy':np.__version__,'pandas':pd.__version__,'threadpools':threadpool_info()},
      'wall_seconds':round(time.time()-start,3),'cpu_seconds':round(time.process_time()-cpu,3),'peak_rss_bytes':int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}
    dumpj(RUN/'FIT_RECEIPT.json',report);print(json.dumps({'stage':'LOCAL_INCREMENT_SAVED','fit_rows':len(fit),'fit_stocks':int(fit.ts_code.nunique()),'posterior_stocks':len(changes),'parameter_delta':delta,'model_sha256':r.sha(model),'wall_seconds':report['wall_seconds'],'peak_rss_bytes':report['peak_rss_bytes']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
