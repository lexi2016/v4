"""Fresh-process restricted load and targeted replay checks; no training."""
import json,sys
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
import runtime as r
from canary_continue import maturity_mask

ROOT=r.OUT;RUN=ROOT/'full_hard_replay_v1';SRC=ROOT/'inputs/HARD_CANDIDATE_87.parquet';PROV=ROOT/'inputs/HARD_CANDIDATE_PROVENANCE.parquet'
rec=json.loads((RUN/'FIT_RECEIPT.json').read_text());meta=json.loads((RUN/'FIT_COHORT.json').read_text())
assert r.sha(SRC)==rec['candidate_sha256'] and r.sha(PROV)==rec['provenance_sha256']
r.install_compat();old=r.load(r.MODEL/'model_t5_v3_1_all_a.pkl',rec['original_model_sha256']);new=r.load(RUN/'model_t5_hard_replay.pkl',rec['continued_model_sha256'])
df=pd.read_parquet(SRC);p=pd.read_parquet(PROV);fitrows=pd.read_parquet(RUN/'fit_rows_and_masks.parquet');saved=pd.read_parquet(RUN/'same_fit_predictions.parquet')
assert len(df)==303161 and not df.duplicated(['ts_code','signal_date']).any() and df[['ts_code','signal_date']].equals(p[['ts_code','signal_date']])
features=json.loads((r.MODEL/'feature_order_v3_1.json').read_text());p54=[c for c in features if c.startswith('p54_repr_')]
assert len(p54)==11 and df[p54].isna().all().all()
D=df.signal_date;unknown=(D<=20231229)|(D>=20250101);behav=[x for x in features if x.startswith('behav_')];p53=[x for x in features if x.startswith('p53_')]
assert df.loc[unknown,behav+p53].isna().all().all()
assert df.loc[D<=20231229,[x for x in features if x.startswith('pers_eb_')]+['pers_pb_depth_style_index']].isna().all().all()
m=maturity_mask(df,20261015)&np.isfinite(pd.to_numeric(df.ret_t5_pct,errors='coerce'));back=df.domain_source.eq('UNIVERSE_B_DAILY_NO_SIGNAL_PANEL')
m &= df.domain_source.notna()&(back|(pd.to_numeric(df.gap_trading_days,errors='coerce').notna()&df.zge_buypoint_type.notna()))
fit=df.loc[m].copy().reset_index(drop=True);keys=['ts_code','signal_date']
assert len(fit)==meta['fit_rows'] and fit[keys].equals(fitrows[keys]) and fit[keys].equals(saved[keys])
assert fit.exit_date_t5.le(20261015).all() and fit.status_t5.eq('MATURED').all() and fit.signal_date.le(20261015).all()
with threadpool_limits(limits=8):
    op=old.predict(fit);npred=new.predict(fit)
old_diff=float(np.max(np.abs(op-saved.baseline_score.to_numpy(float))));new_diff=float(np.max(np.abs(npred-saved.continued_score.to_numpy(float))))
if old_diff>1e-12 or new_diff>1e-12:raise ValueError('FRESH_PROCESS_PREDICTION_MISMATCH')
assert np.array_equal(old.prep_.medians_,new.prep_.medians_) and np.array_equal(old.prep_.means_,new.prep_.means_) and np.array_equal(old.prep_.stds_,new.prep_.stds_)
assert len(new.gbdt_.trees_)==len(old.gbdt_.trees_)+10 and np.linalg.norm(new.ridge_.coef_-old.ridge_.coef_)>0 and np.linalg.norm(new.rff_.coef_-old.rff_.coef_)>0
u=pd.read_parquet(RUN/'posterior_before_after.parquet');assert len(u)==meta['posterior_stocks'] and u.ts_code.is_unique
for _,row in u.iterrows():
    a=old.stock_posteriors_[row.ts_code];b=new.stock_posteriors_[row.ts_code]
    assert int(a['n_matured_fit'])==int(b['n_matured_fit'])==int(row.prior_n_matured_fit_preserved)
    assert abs(float(a['alpha_post'])-row.alpha_before)<1e-15 and abs(float(b['alpha_post'])-row.alpha_after)<1e-15
    for j in range(12):
        assert abs(float(a['beta_post'][j])-row[f'beta{j:02d}_before'])<1e-15
        assert abs(float(b['beta_post'][j])-row[f'beta{j:02d}_after'])<1e-15
    if row.z11_observed_rows==0:assert abs(float(b['beta_post'][11])-float(a['beta_post'][11]))<1e-15
# Recompute the posterior for three deterministic representative profiles,
# covering an observed z11, an unknown z11, and maximal row count.
selected=[str(u.loc[u.z11_observed_rows.gt(0),'ts_code'].iloc[0]),str(u.loc[u.z11_observed_rows.eq(0),'ts_code'].iloc[0]),str(u.loc[u.rows.idxmax(),'ts_code'])]
checks=[]
for tc in dict.fromkeys(selected):
    x=fitrows.ts_code.eq(tc)&fitrows.posterior_eligible_13_known_inputs;s=fit.loc[x].copy().reset_index(drop=True);Y=fitrows.loc[x,'hard_rank_target'].to_numpy(float)
    obs=np.isfinite(s.p53_jcb_rs_5d_excess.to_numpy(float));s.loc[~obs,'p53_jcb_rs_5d_excess']=0.0;Z=new.build_structural_design_matrix_12d(s);Z[~obs,11]=0.0
    prev=old.stock_posteriors_[tc];a=float(prev['alpha_post']);b=np.asarray(prev['beta_post'],dtype=float);n=len(s);bars=int(prev.get('total_bars',0));low=.25 if bars<60 else (.60 if n<6 else 1.)
    lam=n/(n+new.tau_intercept)*low;alpha=float(np.clip(lam*float(np.mean(Y))+(1-lam)*a,-.025,.025));tau=new.tau_slope/max(.15,low)
    beta=np.linalg.solve(Z.T@Z+tau*np.eye(12),Z.T@(Y-alpha)+tau*b);beta[3]=np.clip(beta[3],.002,.032);beta[4]=np.clip(beta[4],-.048,-.010);beta[5]=np.clip(beta[5],-.038,-.006);beta=np.clip(beta,-.048,.038)
    if not obs.any():beta[11]=b[11]
    maxd=float(np.max(np.abs(beta-new.stock_posteriors_[tc]['beta_post'])));assert maxd<1e-12 and abs(alpha-new.stock_posteriors_[tc]['alpha_post'])<1e-12
    checks.append({'ts_code':tc,'rows':n,'z11_observed_rows':int(obs.sum()),'max_beta_error':maxd})
result={'status':'FRESH_PROCESS_TECHNICAL_CHECK_PASS_REVIEW_PENDING','python':sys.executable,'input_rows':len(df),'fit_rows':len(fit),'fit_stocks':int(fit.ts_code.nunique()),
 'baseline_max_abs_prediction_diff':old_diff,'continued_max_abs_prediction_diff':new_diff,'all_candidate_known_future_masks':'PASS',
 'maturity_key_alignment':'PASS','frozen_preprocessor_and_parameter_delta':'PASS','posterior_all_stored_values_vs_original':'PASS',
 'posterior_recomputed_representative_cases':checks,'all_dimensions':rec['dimensions'],
 'continued_model_sha256':rec['continued_model_sha256'],'fit_receipt_sha256':r.sha(RUN/'FIT_RECEIPT.json'),
 'scope':'REPLAY_ADAPTATION_ONLY; no PIT, teacher/old weight clean, calibration, holdout, strategy, BUY, or production conclusion'}
(RUN/'FRESH_PROCESS_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps(result,ensure_ascii=False))
