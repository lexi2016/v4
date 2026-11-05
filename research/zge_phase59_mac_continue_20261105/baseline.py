"""Frozen same-input CPU inference using strict pickle globals in a fresh process."""
import argparse,json
import numpy as np
import pandas as pd
import runtime as r

SAMPLE=r.MODEL/'sample_all_a_panel_2500.parquet'
FEATURES=r.MODEL/'feature_order_v3_1.json'
def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['reference','compat'],required=True);args=p.parse_args()
    if args.mode=='reference':r.install_original_reference()
    else:r.install_compat()
    if r.sha(SAMPLE)!='7139943f56ed6bc934b9c96b04d772bbe33648efa108f8f4e4fb56bddeac3b95':raise ValueError('SAMPLE_HASH_DRIFT')
    if r.sha(FEATURES)!='6d4e8f60a7854f1895976e1d462975d4645fc0dc01d2b92661d8111b28172325':raise ValueError('FEATURE_ORDER_HASH_DRIFT')
    features=json.loads(FEATURES.read_text());assert len(features)==87 and len(set(features))==87
    df=pd.read_parquet(SAMPLE,columns=list(dict.fromkeys(['ts_code','signal_date']+features)))
    if len(df)!=2500 or df.duplicated(['ts_code','signal_date']).any():raise ValueError('SAMPLE_COUNT_OR_KEY_MISMATCH')
    if not df.ts_code.astype(str).str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():raise ValueError('SAMPLE_MARKET_OR_CODE_INVALID')
    models={}
    for k in ('t1','t2','t5'):
        name=f'model_{k}_v3_1_all_a.pkl';models[k]=r.load(r.MODEL/name,r.MODEL_SHA[name]);m=models[k]
        if m.feat_cols!=features or m.n_random_effects!=12:raise ValueError('MODEL_FEATURE_OR_POSTERIOR_DIMENSION_MISMATCH')
    failname='model_fail_risk_v3_1_all_a.pkl';calname='calibrators_pava_platt_v3_1.pkl'
    fail=r.load(r.MODEL/failname,r.MODEL_SHA[failname]);cals=r.load(r.MODEL/calname,r.MODEL_SHA[calname])
    out=df[['ts_code','signal_date']].copy();out.insert(0,'sample_row_id',np.arange(len(df),dtype='int64'))
    for k,model in models.items():out[f'score_{k}']=model.predict(df)
    out['score_fail']=fail.predict(df)
    out['provided_cal_t5']=cals['pava']['T5_WIN_NET25_V3_1'].predict_proba(out.score_t5.to_numpy())
    out['provided_cal_fail']=cals['pava']['STRUCT_FAIL_5D_RISK_V3_1'].predict_proba(out.score_fail.to_numpy())
    if not np.isfinite(out.drop(columns=['ts_code','signal_date']).to_numpy(dtype=float)).all():raise ValueError('BASELINE_NONFINITE_PREDICTION')
    dest=r.OUT/f'baseline_{args.mode}.parquet';out.to_parquet(dest,index=False,compression='zstd')
    receipt={'mode':args.mode,'rows':len(df),'symbols':int(df.ts_code.nunique()),'signal_date_min':str(df.signal_date.min()),'signal_date_max':str(df.signal_date.max()),
      'sample_sha256':r.sha(SAMPLE),'feature_order_sha256':r.sha(FEATURES),'model_sha256':r.MODEL_SHA,
      'model_posteriors_counts':{k:len(m.stock_posteriors_) for k,m in models.items()},'model_dimensions':{k:m.n_random_effects for k,m in models.items()},
      'baseline_output':str(dest),'baseline_output_sha256':r.sha(dest),'scope':'SAMPLE_2500_ENGINEERING_INFERENCE_NOT_FULL_TRAINING',
      'calibrators':'ORIGINAL_PACKAGE_ONLY_NOT_NEWLY_VALIDATED','pickle_loader':'EXACT_HASH_AND_RESTRICTED_CLASS_ALLOWLIST','native_library':'DISABLED'}
    (r.OUT/f'BASELINE_{args.mode.upper()}_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()
