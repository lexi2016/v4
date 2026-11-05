"""Audit the exact STEP7 base dataset and resolve shared-name sample conflicts."""
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import runtime as r

root=r.OUT;second=root/'inputs/P5_9_UNIFIED_ALL_A_DATASET.parquet';receipt=json.loads((root/'inputs/SECOND_PANEL_BYTE_READBACK.json').read_text())
assert second.stat().st_size==receipt['bytes']==140847288
assert receipt['sha256']=='81ae29d7fc4c887ff2b778223c890e58d5bd4cce43e24525747ebafb5dc0e8cf'
pf=pq.ParquetFile(second);assert pf.metadata.num_rows==303161
features=json.loads((r.MODEL/'feature_order_v3_1.json').read_text());names=set(pf.schema_arrow.names)
present=[x for x in features if x in names];missing=[x for x in features if x not in names]
extras=['ts_code','signal_date','exit_date_t5','status_t5','ret_t5_pct','domain_source','gap_trading_days','zge_buypoint_type']
cols=list(dict.fromkeys(extras+present));frame=pd.read_parquet(second,columns=cols);sample=pd.read_parquet(r.MODEL/'sample_all_a_panel_2500.parquet',columns=cols)
if len(frame)!=303161 or frame.duplicated(['ts_code','signal_date']).any():raise ValueError('SECOND_DUPLICATE_OR_ROW_COUNT')
if not frame.ts_code.astype(str).str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():raise ValueError('SECOND_MARKET_OR_CODE_INVALID')
mainkeys=pd.read_parquet(root/'inputs/FULL_BASE_49_KEYED_PROJECTION.parquet',columns=['ts_code','signal_date'])
keymatch=frame[['ts_code','signal_date']].merge(mainkeys,on=['ts_code','signal_date'],how='outer',validate='one_to_one',indicator=True)
if not keymatch['_merge'].eq('both').all():raise ValueError('MAIN_SECOND_KEY_SET_CONFLICT')
joined=sample.merge(frame,on=['ts_code','signal_date'],how='left',validate='one_to_one',suffixes=('_sample','_second'),indicator=True)
matched=joined['_merge'].eq('both');mismatches={}
for c in [x for x in cols if x not in ('ts_code','signal_date')]:
    a=joined.loc[matched,f'{c}_sample'];b=joined.loc[matched,f'{c}_second']
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
        x=pd.to_numeric(a,errors='coerce').to_numpy(dtype=float,na_value=np.nan);y=pd.to_numeric(b,errors='coerce').to_numpy(dtype=float,na_value=np.nan)
        neq=~np.isclose(x,y,rtol=0,atol=1e-12,equal_nan=True)
    else:neq=(a.astype('string').fillna('<NULL>')!=b.astype('string').fillna('<NULL>')).to_numpy(dtype=bool)
    mismatches[c]=int(neq.sum())
present_in_sample=joined.loc[matched];r2_changed=int((present_in_sample['rev_r2_engulf_flag_sample']!=present_in_sample['rev_r2_engulf_flag_second']).sum())
df_fit=frame.loc[pd.to_numeric(frame.signal_date,errors='coerce').le(20261008)].copy()
mat=df_fit.status_t5.eq('MATURED')&pd.to_numeric(df_fit.ret_t5_pct,errors='coerce').notna()
end=pd.to_numeric(df_fit.exit_date_t5,errors='coerce');signal=pd.to_numeric(df_fit.signal_date,errors='coerce')
cutoff_after=mat&end.gt(20261008);missing_end=mat&end.isna();backwards=mat&end.lt(signal)
projection=root/'inputs/SECOND_BASE_66_KEYED_PROJECTION.parquet';frame.to_parquet(projection,index=False,compression='zstd')
badcols={k:v for k,v in mismatches.items() if v}
out={'status':'EXACT_SAMPLE_VALUES_MATCH' if matched.all() and not badcols else 'SEMANTIC_CONFLICT_SAMPLE_SECOND',
 'source_path':str(second),'source_sha256':receipt['sha256'],'source_hash_method':'PARENT_PART_REASSEMBLY_READBACK',
 'source_rows':len(frame),'main_key_set':'ONE_TO_ONE_EQUAL','full_stocks':int(frame.ts_code.nunique()),
 'sample_rows':len(sample),'sample_keys_found':int(matched.sum()),'sample_keys_missing':int((~matched).sum()),
 'feature_count':len(features),'exact_feature_names_present':len(present),'exact_feature_names_missing':missing,
 'shared_column_mismatches':badcols,'sample_vs_second_rev_r2_mismatches':r2_changed,
 'source_step7_rule':'signal_date<=20261008 and status_t5=MATURED/ret_t5 notna; no exit_date_t5 cutoff in pinned STEP7',
 'source_script_implied_fit_rows':len(df_fit),'source_script_implied_t5_matured_rows':int(mat.sum()),
 'source_script_implied_matured_exit_date_max':None if not mat.any() else int(end.loc[mat].max()),
 'source_script_implied_matured_exit_after_20261008_count':int(cutoff_after.sum()),
 'matured_missing_exit_count':int(missing_end.sum()),'matured_exit_before_signal_count':int(backwards.sum()),
 'actual_cloud_execution_identity':'CANNOT_CONFIRM_FROM_SOURCE_ALONE','baseline_known_label_end':'SOURCE_SCRIPT_IMPLIED_NOT_CERTIFIED',
 'projection_path':str(projection),'projection_sha256':r.sha(projection),'projection_columns':cols,
 'training_eligibility':'CANNOT_CONFIRM_21_FEATURES_AND_TIME_LINEAGE','fit':'NOT_RUN'}
(root/'SECOND_INPUT_AUDIT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:out[k] for k in ['status','main_key_set','sample_keys_found','exact_feature_names_present','shared_column_mismatches','source_script_implied_fit_rows','source_script_implied_t5_matured_rows','source_script_implied_matured_exit_date_max','source_script_implied_matured_exit_after_20261008_count','matured_missing_exit_count','matured_exit_before_signal_count','projection_sha256']},ensure_ascii=False))
