"""Fresh-process prediction parity and local label identity verification."""
import json,sys
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
import runtime as r

ROOT=r.OUT;RUN=ROOT/'local_increment_v1';PARENT=ROOT/'full_hard_replay_v1/model_t5_hard_replay.pkl'
DATA=ROOT/'inputs/HARD_CANDIDATE_87.parquet';OVER=ROOT/'inputs/LOCAL_LABEL_OVERLAY_R3.parquet'
SESSION='/Users/lexi/Desktop/学习/agents调试/Z哥方法论/pullback_model_design_20261104/training_v1/full/observed_a_sessions.parquet'
rec=json.loads((RUN/'FIT_RECEIPT.json').read_text());assert r.sha(DATA)==rec['candidate_sha256'] and r.sha(OVER)==rec['local_label_overlay_sha256']
r.install_compat();old=r.load(PARENT,rec['parent_model_sha256']);new=r.load(RUN/'model_t5_local_increment.pkl',rec['local_model_sha256'])
src=pd.read_parquet(DATA);o=pd.read_parquet(OVER);fitrows=pd.read_parquet(RUN/'fit_rows_and_masks.parquet');pred=pd.read_parquet(RUN/'same_fit_predictions.parquet');keys=['ts_code','signal_date']
assert len(o)==6664 and not o.duplicated(keys).any() and o.cloud_original_status_t5.eq('PENDING').all()
unknown=~o.local_label_status.eq('KNOWN_LOCAL_LABEL');assert o.loc[unknown,'local_ret_t5_pct'].isna().all()
exclude={'000831.SZ','000972.SZ','002129.SZ','002623.SZ','002827.SZ','605258.SH','688121.SH'}
assert o.loc[o.ts_code.isin(exclude),'local_label_status'].eq('EXCLUDED_RETAINED_ORIGINAL_BASIS').all()
known=o.loc[~unknown].copy().reset_index(drop=True);assert len(known)==6602 and not known.ts_code.isin(exclude).any()
ss=pd.read_parquet(SESSION).trade_date.to_numpy(dtype='int64');ix=np.searchsorted(ss,known.signal_date.to_numpy(dtype='int64'))
assert (ss[ix]==known.signal_date.to_numpy()).all() and (ss[ix+1]==known.local_entry_date.to_numpy()).all() and (ss[ix+6]==known.local_exit_date.to_numpy()).all()
assert known.local_exit_date.between(20261016,20261104).all() and known.signal_date.between(20261009,20261015).all()
cols=['local_entry_open','local_exit_open','local_entry_volume','local_exit_volume'];assert np.isfinite(known[cols].to_numpy(float)).all() and (known[cols].to_numpy(float)>0).all()
assert known.local_entry_valid.eq(True).all() and known.local_exit_valid.eq(True).all()
assert np.allclose((known.local_exit_open/known.local_entry_open-1)*100,known.local_ret_t5_pct,rtol=0,atol=1e-12)
# Compare cloud raw status/return/dates/entry directly, preserving NA exactly.
cloudpath=ROOT/'inputs/P5_9_ALL_A_UNIFIED_PANEL_303161.parquet';cloud=pd.read_parquet(cloudpath,columns=keys+['status_t5','ret_t5_pct','entry_date','entry_open_px','exit_date_t5'])
raw=o.merge(cloud,on=keys,how='left',validate='one_to_one',indicator=True);assert raw['_merge'].eq('both').all()
for c in ['status_t5','ret_t5_pct','entry_date','entry_open_px','exit_date_t5']:
    a=raw['cloud_original_'+c];b=raw[c]
    assert (a.eq(b)|(a.isna()&b.isna())).fillna(False).all(),c
fit=known.merge(src,on=keys,how='left',validate='one_to_one',indicator=True);assert fit['_merge'].eq('both').all();fit=fit.drop(columns='_merge')
bg=fit.domain_source.eq('UNIVERSE_B_DAILY_NO_SIGNAL_PANEL');w=fit.domain_source.notna()&(bg|(pd.to_numeric(fit.gap_trading_days,errors='coerce').notna()&fit.zge_buypoint_type.notna()))
fit=fit.loc[w].reset_index(drop=True);assert fit[keys].equals(fitrows[keys]) and fit[keys].equals(pred[keys]) and len(fit)==6602
prior=pd.read_parquet(ROOT/'full_hard_replay_v1/fit_rows_and_masks.parquet',columns=keys);assert len(fit[keys].merge(prior,on=keys,how='inner'))==0
with threadpool_limits(limits=8):a=old.predict(fit);b=new.predict(fit)
ad=float(np.max(np.abs(a-pred.parent_score.to_numpy(float))));bd=float(np.max(np.abs(b-pred.increment_score.to_numpy(float))));assert ad<=1e-12 and bd<=1e-12
assert np.array_equal(old.prep_.medians_,new.prep_.medians_) and np.array_equal(old.prep_.means_,new.prep_.means_) and np.array_equal(old.prep_.stds_,new.prep_.stds_)
assert len(new.gbdt_.trees_)==len(old.gbdt_.trees_)+10 and np.linalg.norm(old.ridge_.coef_-new.ridge_.coef_)>0 and np.linalg.norm(old.rff_.coef_-new.rff_.coef_)>0
p=pd.read_parquet(RUN/'posterior_before_after.parquet');assert len(p)==5530 and p.ts_code.is_unique
for _,row in p.iterrows():
    before=old.stock_posteriors_[row.ts_code];after=new.stock_posteriors_[row.ts_code]
    assert before['n_matured_fit']==after['n_matured_fit']==row.prior_n_matured_fit_preserved
    for j in range(12):
        assert abs(float(before['beta_post'][j])-row[f'beta{j:02d}_before'])<1e-15 and abs(float(after['beta_post'][j])-row[f'beta{j:02d}_after'])<1e-15
    assert after['beta_post'][11]==before['beta_post'][11] and row.z11_observed_rows==0
# Recompute two deterministic posterior cases (few-row and max-row).
checks=[]
for tc in dict.fromkeys([str(p.ts_code.iloc[0]),str(p.loc[p.new_matured_rows.idxmax(),'ts_code'])]):
    select=fitrows.ts_code.eq(tc)&fitrows.posterior_eligible_13_known_inputs;f=fit.loc[select].copy().reset_index(drop=True);Y=fitrows.loc[select,'hard_rank_target'].to_numpy(float);f['p53_jcb_rs_5d_excess']=0.0
    z=new.build_structural_design_matrix_12d(f);z[:,11]=0.;prior=old.stock_posteriors_[tc];aa=float(prior['alpha_post']);bb=np.asarray(prior['beta_post'],dtype=float);n=len(f);bars=int(prior.get('total_bars',0));low=.25 if bars<60 else (.60 if n<6 else 1.);lam=n/(n+new.tau_intercept)*low
    alpha=float(np.clip(lam*float(np.mean(Y))+(1-lam)*aa,-.025,.025));tau=new.tau_slope/max(.15,low);beta=np.linalg.solve(z.T@z+tau*np.eye(12),z.T@(Y-alpha)+tau*bb)
    beta[3]=np.clip(beta[3],.002,.032);beta[4]=np.clip(beta[4],-.048,-.010);beta[5]=np.clip(beta[5],-.038,-.006);beta=np.clip(beta,-.048,.038);beta[11]=bb[11]
    err=float(np.max(np.abs(beta-new.stock_posteriors_[tc]['beta_post'])));assert err<=1e-12 and abs(alpha-new.stock_posteriors_[tc]['alpha_post'])<=1e-12
    checks.append({'ts_code':tc,'rows':n,'max_beta_error':err})
result={'status':'FRESH_PROCESS_LOCAL_INCREMENT_CHECK_PASS_QA_PENDING','python':sys.executable,'tail_rows':len(o),'unknown_excluded_rows':int(unknown.sum()),'fit_rows':len(fit),'fit_stocks':int(fit.ts_code.nunique()),
 'baseline_parent_max_abs_prediction_diff':ad,'continued_max_abs_prediction_diff':bd,'original_cloud_fields_preserved':'PASS','local_session_price_volume_maturity':'PASS',
 'all_unknown_label_values_remain_nan':'PASS','excluded_seven_codes':'PASS','prior_fit_overlap':0,'all_saved_posterior_values_match':'PASS','posterior_recomputed_representative_cases':checks,
 'z11_unknown_and_parent_prior_preserved':'PASS','model_sha256':rec['local_model_sha256'],'fit_receipt_sha256':r.sha(RUN/'FIT_RECEIPT.json'),
 'scope':'LOCAL SOURCE MIGRATION RESEARCH, DIRECTION_ONLY; calendar/PIT/cloud equality/calibration/holdout/strategy/BUY CANNOT_CONFIRM'}
(RUN/'FRESH_PROCESS_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps(result,ensure_ascii=False))
