"""Build a lineage-bounded replay candidate; no fitting or predictions.

Producer as-of claims do not establish historical first availability. All
reconstructed or retained values are REPLAY_ONLY, not PIT-certified.
"""
import json
import numpy as np
import pandas as pd
import runtime as r

ROOT=r.OUT
FID=ROOT/'inputs/FIDELITY_87_FEATURES.parquet'
PROF=r.MODEL/'per_stock_adaptive_posteriors_12d_5576.parquet'
FEATURES=json.loads((r.MODEL/'feature_order_v3_1.json').read_text())
assert r.sha(FID)=='92801c28f9a0c96300dda344d0c7461f4886f88ec1a87aead987c3a0e2975cb5'
assert r.sha(PROF)=='dfa69f36888f8f2f451e7f33e096c1677556521c20c155536c86592e127154cb'
df=pd.read_parquet(FID);keys=['ts_code','signal_date']; assert len(df)==303161 and not df.duplicated(keys).any()
if not df.ts_code.astype(str).str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():raise ValueError('INVALID_A_SHARE_CODE')
D=pd.to_numeric(df.signal_date,errors='coerce');validdate=pd.to_datetime(D.astype('Int64').astype('string'),format='%Y%m%d',errors='coerce').notna()
if not validdate.all():raise ValueError('BAD_SIGNAL_DATE')
# More conservative later purge_end from delivered 5.8 source; actual execution
# SHA and first availability have NOT been proven. 2021-23 excluded even where
# 2022H2 teacher might have used an earlier half.
cut=np.select([D.le(20231229),D.le(20240628),D.le(20241231),D.le(20250630),D.le(20251231),D.le(20260630),D.le(20261015)],
              [20231229,20231229,20240628,20241231,20250630,20251231,20260630],default=99999999)
teacher_valid=D.gt(20231229)&D.gt(cut)&D.le(20261015)
# W1 and W2 as-of are declared label windows, not proven release times.
w1=D.gt(20231229)&D.lt(20250101);w2=D.gt(20241231)
behav_unusable=~w1  # Full-2026 profile first availability is not proven.
prof=pd.read_parquet(PROF).set_index('ts_code');pos=prof.index.get_indexer(df.ts_code)
if (pos<0).any() or not prof.index.is_unique:raise ValueError('PROFILE_KEY_MISMATCH')
field_to_source={'pers_eb_keyk_ret5_edge':'alpha_i','pers_eb_touch_white_win_edge':'beta_pb1',
 'pers_eb_touch_yellow_win_edge':'beta_pb2','pers_eb_touch_keyk_bot_win_edge':'beta_pb3',
 'pers_eb_b1_win_edge':'beta_j_wash','pers_eb_b2_win_edge':'beta_b2',
 'pers_eb_buildup_win_edge':'beta_jcb','pers_eb_big_green_fail_diff':'gamma_fail',
 'pers_eb_strong_weak_regime_spread':'beta_yellow'}
for field,source in field_to_source.items():
    a=pd.to_numeric(prof['w1_'+source],errors='coerce').to_numpy(float)[pos]
    b=pd.to_numeric(prof['w2_'+source],errors='coerce').to_numpy(float)[pos]
    df[field]=np.where(w1,a,np.where(w2,b,np.nan))
# Both the raw 2024+ habit and 2024/2025+ profile source windows are declared,
# but their peer metadata and actual availability remain uncertified.
df.loc[~(w1|w2),'pers_pb_depth_style_index']=np.nan
behav=[c for c in FEATURES if c.startswith('behav_')]
p53=[c for c in FEATURES if c.startswith('p53_')]
assert len(behav)==6 and len(p53)==7
# The provenance text only binds behav dependency clearly for one P53 field;
# conservatively mask all P53 fields when the profile is future/unknown.
df.loc[behav_unusable,behav+p53]=np.nan
p54=[c for c in FEATURES if c.startswith('p54_repr_')]; assert len(p54)==11
df.loc[~teacher_valid,p54]=np.nan
# Producer calculates mean/std on the entire prediction fold, including future dates.
df['p54_repr_gbdt_stage_margin']=np.nan
masks=pd.DataFrame({'ts_code':df.ts_code,'signal_date':df.signal_date,
 'teacher_producer_cutoff_conservative':cut,'teacher_cutoff_before_signal_replay_only':teacher_valid,
 'profile_window':np.where(w1,'W1_ASOF_20231229_REPLAY_ONLY',np.where(w2,'W2_ASOF_20241231_REPLAY_ONLY','UNKNOWN')),
 'profile_first_available':'CANNOT_CONFIRM','behavior_fields_masked':behav_unusable,
 'p53_fields_masked':behav_unusable,'teacher_all_fields_masked':~teacher_valid,
 'teacher_fold_margin_masked':True,'habit_profile_masked':~(w1|w2)})
# The feature values remain null. Frozen model preprocessor handles nulls only
# inside inference/fit; its imputed values are not counted as observed.
out=ROOT/'inputs/REPLAY_CANDIDATE_87.parquet';df.to_parquet(out,index=False,compression='zstd')
mp=ROOT/'inputs/REPLAY_CANDIDATE_PROVENANCE.parquet';masks.to_parquet(mp,index=False,compression='zstd')
nulls={c:int(pd.to_numeric(df[c],errors='coerce').isna().sum()) for c in FEATURES}
counts={}
for y,ix in D.groupby(D//10000).groups.items():
    s=masks.loc[ix]; counts[str(int(y))]={'rows':len(s),'teacher_cutoff_before_signal_replay_only':int(s.teacher_cutoff_before_signal_replay_only.sum()),
      'behavior_masked':int(s.behavior_fields_masked.sum()),'p53_masked':int(s.p53_fields_masked.sum()),
      'profile_unknown':int(s.profile_window.eq('UNKNOWN').sum())}
coverage={'status':'REPLAY_CANDIDATE_CREATED_NOT_PIT_CERTIFIED','rows':len(df),'stocks':int(df.ts_code.nunique()),
 'signal_range':[int(D.min()),int(D.max())],'feature_count':len(FEATURES),'per_feature_unknown_counts':nulls,
 'by_year':counts,'teacher_cutoff_policy':'max of delivered phase58 source and producer lineage; exact execution source SHA and first_available CANNOT_CONFIRM',
 'teacher_margin':'ALL_UNKNOWN_FOLD_WIDE_FUTURE_MEAN_STD','profile_rule':'D<=20231229 UNKNOWN; 2024 W1; >=2025 W2; first_available CANNOT_CONFIRM',
 'behavior_rule':'2024 after 20231229 source profile retained REPLAY_ONLY; all other dates UNKNOWN',
 'p53_rule':'all 7 UNKNOWN where behavior unavailable because individual dependencies not independently bound',
 'cohort_rule':'no rows dropped in candidate; later fit excludes immature/unknown targets and logs eligibility',
 'parent_sha256':r.sha(FID),'candidate_path':str(out),'candidate_sha256':r.sha(out),
 'provenance_path':str(mp),'provenance_sha256':r.sha(mp),'profile_sha256':r.sha(PROF),
 'source_feature_default_flags_path':str(ROOT/'inputs/FIDELITY_SOURCE_DEFAULT_FLAGS.parquet'),
 'known_limits':['REPLAY_ADAPTATION','original model and frozen imputer already exposed historical data','feature source and first availability not independently PIT certified',
 'original teacher prediction provenance has unresolved source SHA/cutoff conflict','no rows or imputed features are called observed'],
 'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
(ROOT/'CANDIDATE_REPORT.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({k:coverage[k] for k in ('status','rows','stocks','by_year','candidate_sha256','provenance_sha256')},ensure_ascii=False))
