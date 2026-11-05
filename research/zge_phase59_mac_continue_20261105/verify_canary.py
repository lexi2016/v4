"""Fresh-process checks for the saved Phase5.9 sample-only continuation."""
import io,json,pickle,sys
import numpy as np
import pandas as pd
import runtime as r
from canary_continue import CUTOFF,STRUCT,maturity_mask,weights_function

d=r.OUT/'canary_v1';receipt=json.loads((d/'FIT_RECEIPT.json').read_text());r.install_compat()
try:r.RestrictedUnpickler(io.BytesIO(pickle.dumps(eval,protocol=4))).load();raise AssertionError('UNALLOWED_GLOBAL_ACCEPTED')
except pickle.UnpicklingError:pass
model=r.load(receipt['continued_model_path'],receipt['continued_model_sha256'])
original=r.load(r.MODEL/'model_t5_v3_1_all_a.pkl',r.MODEL_SHA['model_t5_v3_1_all_a.pkl'])
fit=pd.read_parquet(d/'fit_rows.parquet');updates=pd.read_parquet(d/'posterior_before_after.parquet');pred=pd.read_parquet(d/'same_sample_predictions.parquet')
sample=pd.read_parquet(r.MODEL/'sample_all_a_panel_2500.parquet');baseline=pd.read_parquet(r.OUT/'baseline_compat.parquet')
if not maturity_mask(fit,CUTOFF).all():raise AssertionError('UNMATURED_ROW_ENTERED_FIT')
if not np.isfinite(fit.loc[fit.posterior_eligible_12d,STRUCT].to_numpy(dtype='float64')).all():raise AssertionError('UNKNOWN_POSTERIOR_FIELD_USED')
if not np.allclose(weights_function()(fit,'W6_STRATIFIED_HYBRID_WEIGHT'),fit.sample_w6_weight.to_numpy(),rtol=1e-12,atol=1e-12):raise AssertionError('W6_WEIGHT_MISMATCH')
keys=sample[['ts_code','signal_date','exit_date_t5','status_t5','ret_t5_pct']]
fitkeys=fit[['ts_code','signal_date','exit_date_t5','status_t5','ret_t5_pct']]
check=fitkeys.merge(keys,on=['ts_code','signal_date'],suffixes=('_fit','_source'),validate='one_to_one',how='left')
for col in ('exit_date_t5','status_t5','ret_t5_pct'):
    if not check[f'{col}_fit'].equals(check[f'{col}_source']):raise AssertionError('INPUT_LABEL_VALUE_MISMATCH:'+col)
future=fit.head(1).copy();future['exit_date_t5']=20261009;future['status_t5']='MATURED';future['ret_t5_pct']=1e9
if maturity_mask(future,CUTOFF).any():raise AssertionError('FUTURE_LABEL_ACCEPTED')
for row in updates.itertuples(index=False):
    old=original.stock_posteriors_[row.ts_code];new=model.stock_posteriors_[row.ts_code]
    for j in range(12):
        if not np.isclose(old['beta_post'][j],getattr(row,f'beta{j:02d}_before'),rtol=0,atol=1e-15):raise AssertionError('PRIOR_POSTERIOR_MISMATCH')
        if not np.isclose(new['beta_post'][j],getattr(row,f'beta{j:02d}_after'),rtol=0,atol=1e-15):raise AssertionError('NEW_POSTERIOR_MISMATCH')
    if new['n_matured_fit']!=old['n_matured_fit']:raise AssertionError('REPLAY_COUNT_AS_UNIQUE')
if len(model.stock_posteriors_)!=len(original.stock_posteriors_) or len(model.stock_posteriors_)!=5576:raise AssertionError('POSTERIOR_COVERAGE_CHANGED')
score=model.predict(sample);delta=np.abs(score-pred.continued_score_t5.to_numpy());base_delta=np.abs(baseline.score_t5.to_numpy()-pred.baseline_score_t5.to_numpy())
if delta.max()>1e-12 or base_delta.max()>1e-12:raise AssertionError('FRESH_PROCESS_PREDICTION_MISMATCH')
drift=score-baseline.score_t5.to_numpy()
result={'status':'PASS_SAMPLE_ONLY','python':sys.executable,'fresh_process_load_predict_max_abs_difference':float(delta.max()),
 'baseline_input_match_max_abs_difference':float(base_delta.max()),'future_label_exclusion':'PASS','maturity_and_weight_rule':'PASS',
 'input_label_key_and_value_parity':'PASS','restricted_unknown_pickle_global_rejected':'PASS',
 'updated_stock_count':len(updates),'posterior_dimensions_compared_per_stock':12,'all_other_posteriors_count_preserved':len(model.stock_posteriors_),
 'score_change':{'rows':len(score),'changed_count':int((np.abs(drift)>1e-12).sum()),'mean_abs':float(np.mean(np.abs(drift))),'max_abs':float(np.max(np.abs(drift)))},
 'model_path':receipt['continued_model_path'],'model_sha256':receipt['continued_model_sha256'],'sample_only':True,
 'scope_limitation':'REPLAY_ADAPTATION_ENGINEERING_NOT_FULL_TRAINING_OR_NEW_DATE_INCREMENT'}
(d/'FRESH_PROCESS_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
