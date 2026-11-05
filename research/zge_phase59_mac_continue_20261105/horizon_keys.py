"""Count per-horizon matured keys outside the source STEP7 signal-date filter."""
import json
import pandas as pd
import runtime as r

p=r.OUT/'inputs/P5_9_UNIFIED_ALL_A_DATASET.parquet';cols=['ts_code','signal_date']+[x for h in ('t1','t2','t5') for x in (f'exit_date_{h}',f'status_{h}',f'ret_{h}_pct')]
df=pd.read_parquet(p,columns=cols);assert len(df)==303161 and not df.duplicated(['ts_code','signal_date']).any()
signal=pd.to_numeric(df.signal_date,errors='coerce');present=signal.le(20261008);report={};eligible={}
for horizon in ('t1','t2','t5'):
    end=pd.to_numeric(df[f'exit_date_{horizon}'],errors='coerce');ret=pd.to_numeric(df[f'ret_{horizon}_pct'],errors='coerce')
    mat=df[f'status_{horizon}'].eq('MATURED')&ret.notna();malformed=mat&(end.isna()|end.lt(signal))
    if malformed.any():raise ValueError(f'INVALID_MATURE_LABEL_{horizon}:{int(malformed.sum())}')
    fresh=~present&signal.le(20261015)&mat&end.le(20261015);eligible[horizon]=fresh
    report[horizon]={'original_step7_all_fit_keys':int(present.sum()),'original_step7_matured_label_keys':int((present&mat).sum()),
      'original_step7_matured_max_label_end':None if not (present&mat).any() else int(end[present&mat].max()),
      'new_keys_matured_by_20261015':int(fresh.sum()),'new_stocks':int(df.loc[fresh,'ts_code'].nunique()),
      'new_signal_min':None if not fresh.any() else int(signal[fresh].min()),'new_signal_max':None if not fresh.any() else int(signal[fresh].max()),
      'label_end_max':None if not fresh.any() else int(end[fresh].max()),'status':'INCREMENTAL_KEYS_ALREADY_EXPOSED_HISTORY'}
union=eligible['t1']|eligible['t2']|eligible['t5'];out=df.loc[union].copy()
for horizon in ('t1','t2','t5'):out[f'{horizon}_new_matured_20261015']=eligible[horizon].loc[union].to_numpy()
path=r.OUT/'inputs/HORIZON_NEW_KEYS.parquet';out.to_parquet(path,index=False,compression='zstd')
res={'status':'MATURED_KEY_COUNTS_ONLY_NO_FIT','scope':'CLOUD_SOURCE_ASOF_20261015_EXPOSED_HISTORY','source_sha256':'81ae29d7fc4c887ff2b778223c890e58d5bd4cce43e24525747ebafb5dc0e8cf',
 'original_fit_membership':'STEP7 signal_date<=20261008; all rows had positive t5-based weights','by_horizon':report,
 'key_union_rows':len(out),'key_union_path':str(path),'key_union_sha256':r.sha(path),'PIT_or_evaluation_status':'CANNOT_CONFIRM'}
(r.OUT/'HORIZON_NEW_KEYS.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n');print(json.dumps(res,ensure_ascii=False))
