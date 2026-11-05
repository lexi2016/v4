"""Bind the downloaded 303161-row projection against the frozen 2500 sample.

This tests identity, dates, keys and exact shared feature values. It does not
map missing names or claim the input is PIT, complete or eligible for fit.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import runtime as r

root=r.OUT;full=root/'inputs/P5_9_ALL_A_UNIFIED_PANEL_303161.parquet';parent=root/'inputs/FULL_PANEL_BYTE_READBACK.json'
receipt=json.loads(parent.read_text());assert full.stat().st_size==receipt['bytes']==246384290
assert receipt['sha256']=='ec10ffc05beec1ffee27cd3afe1c7e44a54cbeba1f705c6f6e633082a78c0a12'
pf=pq.ParquetFile(full);assert pf.metadata.num_rows==303161
features=json.loads((r.MODEL/'feature_order_v3_1.json').read_text());have=set(pf.schema_arrow.names)
present=[x for x in features if x in have];missing=[x for x in features if x not in have]
base={'source_file':str(full),'source_bytes':full.stat().st_size,'source_sha256':'ec10ffc05beec1ffee27cd3afe1c7e44a54cbeba1f705c6f6e633082a78c0a12',
 'sha_method':'REUSED_PARENT_47_PART_REASSEMBLY_READBACK','rows':pf.metadata.num_rows,'schema_columns':len(pf.schema_arrow.names),
 'expected_feature_count':len(features),'exact_name_present':present,'exact_name_missing':missing,'missing_name_count':len(missing),
 'source_semantics_or_pit':'CANNOT_CONFIRM','sample_to_full_key_or_values':'NOT_YET_CHECKED'}
(root/'FULL_SCHEMA_METADATA.json').write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n')
extras=['ts_code','signal_date','exit_date_t5','status_t5','ret_t5_pct','domain_source','gap_trading_days','zge_buypoint_type']
if set(extras)-have:raise ValueError('MISSING_KEY_OR_LABEL_COLUMNS:'+str(sorted(set(extras)-have)))
cols=list(dict.fromkeys(extras+present));full_df=pd.read_parquet(full,columns=cols);sample=pd.read_parquet(r.MODEL/'sample_all_a_panel_2500.parquet',columns=cols)
if len(full_df)!=303161:raise ValueError('FULL_ROWS_MISMATCH')
if full_df.ts_code.isna().any() or not full_df.ts_code.astype(str).str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():raise ValueError('FULL_MARKET_OR_CODE_INVALID')
dups=full_df.duplicated(['ts_code','signal_date'],keep=False)
if dups.any():
    out={'status':'STOP_DUPLICATE_FULL_KEYS','duplicate_rows':int(dups.sum()),'examples':full_df.loc[dups,['ts_code','signal_date','domain_source']].head(20).to_dict('records')}
    (root/'FULL_INPUT_AUDIT_FAILURE.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n');raise ValueError('DUPLICATE_FULL_KEYS')
if sample.duplicated(['ts_code','signal_date']).any():raise ValueError('SAMPLE_KEYS_DUPLICATE')
joined=sample.merge(full_df,on=['ts_code','signal_date'],how='left',validate='one_to_one',suffixes=('_sample','_full'),indicator=True)
matched=joined['_merge'].eq('both');differences={}
for col in [c for c in cols if c not in ('ts_code','signal_date')]:
    x=joined.loc[matched,f'{col}_sample'];y=joined.loc[matched,f'{col}_full']
    if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
        a=pd.to_numeric(x,errors='coerce').to_numpy(dtype=float,na_value=np.nan);b=pd.to_numeric(y,errors='coerce').to_numpy(dtype=float,na_value=np.nan)
        bad=~np.isclose(a,b,rtol=0,atol=1e-12,equal_nan=True)
    else:bad=(x.astype('string').fillna('<NULL>')!=y.astype('string').fillna('<NULL>')).to_numpy(dtype=bool)
    differences[col]=int(bad.sum())
source=root/'inputs/FULL_BASE_49_KEYED_PROJECTION.parquet';full_df.to_parquet(source,index=False,compression='zstd')
badcols={k:v for k,v in differences.items() if v};status='MATCH_EXACT_SHARED_COLUMNS' if matched.all() and not badcols else 'SEMANTIC_CONFLICT_SAMPLE_FULL_SHARED_VALUES'
out={**base,'status':status,'sample_rows':len(sample),'sample_keys_found':int(matched.sum()),'sample_keys_missing':int((~matched).sum()),
 'per_column_mismatch_counts':differences,'mismatch_columns':badcols,'sample_to_full_key_or_values':status,
 'full_unique_stocks':int(full_df.ts_code.nunique()),'full_signal_min':str(full_df.signal_date.min()),'full_signal_max':str(full_df.signal_date.max()),
 'full_t5_status_counts':{str(k):int(v) for k,v in full_df.status_t5.value_counts(dropna=False).items()},
 'projection_path':str(source),'projection_sha256':r.sha(source),'projection_columns':cols,
 'training_eligibility':'CANNOT_CONFIRM_MISSING_FEATURES_AND_SOURCE_CAUSALITY','feature_mapping':'NO_ALIASES_ASSUMED','model_or_fit':'NOT_RUN'}
(root/'FULL_INPUT_AUDIT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n');print(json.dumps({k:out[k] for k in ['status','rows','sample_keys_found','sample_keys_missing','missing_name_count','mismatch_columns','full_unique_stocks','full_signal_min','full_signal_max','full_t5_status_counts','projection_sha256']},ensure_ascii=False))
