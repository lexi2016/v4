"""Preserve the six exact-name sample/full mismatches using the cached projection."""
import json
import pandas as pd
import runtime as r

root=r.OUT;cols=['ts_code','signal_date','domain_source','rev_r2_engulf_flag','exit_date_t5','status_t5','ret_t5_pct']
sample=pd.read_parquet(r.MODEL/'sample_all_a_panel_2500.parquet',columns=cols)
full=pd.read_parquet(root/'inputs/FULL_BASE_49_KEYED_PROJECTION.parquet',columns=cols)
j=sample.merge(full,on=['ts_code','signal_date'],validate='one_to_one',suffixes=('_sample','_full'),indicator=True)
bad=j.loc[j.rev_r2_engulf_flag_sample.ne(j.rev_r2_engulf_flag_full)].copy()
if len(bad)!=6:raise ValueError('MISMATCH_COUNT_CHANGED:'+str(len(bad)))
out=root/'inputs/SAMPLE_FULL_REV_R2_CONFLICT.parquet';bad.to_parquet(out,index=False,compression='zstd')
report={'status':'SEMANTIC_CONFLICT_NOT_RESOLVED','field':'rev_r2_engulf_flag','mismatch_rows':len(bad),
 'mismatch_path':str(out),'mismatch_sha256':r.sha(out),'rows':bad.to_dict('records'),
 'do_not_train_until':'producer final-fit exact values/semantics and canonical provenance are verified'}
(root/'SAMPLE_FULL_REV_R2_CONFLICT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps(report,ensure_ascii=False,default=str))
