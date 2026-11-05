"""Reproduce pinned STEP7's 87D fit-input construction, without fitting.

This deliberately preserves the original retrospective personal-feature
semantics as a fidelity reference. It is not a PIT-corrected training input.
"""
import json
import numpy as np
import pandas as pd
import runtime as r

root=r.OUT;model=r.MODEL;features=json.loads((model/'feature_order_v3_1.json').read_text());assert len(features)==87
second=root/'inputs/SECOND_BASE_66_KEYED_PROJECTION.parquet';main=root/'inputs/P5_9_ALL_A_UNIFIED_PANEL_303161.parquet';profile=model/'per_stock_adaptive_posteriors_12d_5576.parquet'
assert r.sha(second)=='fe279881c75759f0db189d1b89c8dc81c5c7860e1afff8bd07daba17b072f74a'
assert r.sha(profile)=='dfa69f36888f8f2f451e7f33e096c1677556521c20c155536c86592e127154cb'
step=root/'full_reference/src/P5_9_STEP7_PACKAGE_AND_REPORT.py';assert r.sha(step)=='64c001989c1244eebd9350baf4ba4e75cfd2cefca154b3304f9f8f611a4bc63e'
base=pd.read_parquet(second)
keys=['ts_code','signal_date'];rawcols=['p54_emb_pb_qual','p54_emb_rev_r1r4','p54_emb_pb1','p54_emb_pb2','p54_emb_pb3',
 'p54_emb_ret_t5','p54_emb_mae_t10','p54_emb_mfe_t10','p54_emb_fail_risk','p54_emb_gbdt_margin_norm','y_teacher_ret_t5_pit','pb_depth_diff_from_habit']
part=pd.read_parquet(main,columns=keys+rawcols)
if base.duplicated(keys).any() or part.duplicated(keys).any():raise ValueError('FIDELITY_DUPLICATE_KEYS')
df=base.merge(part,on=keys,how='left',validate='one_to_one',indicator=True,sort=False)
if not df['_merge'].eq('both').all():raise ValueError('FIDELITY_P54_KEY_NOT_MATCHED')
df=df.drop(columns='_merge');prof=pd.read_parquet(profile)
if len(prof)!=5576 or prof.ts_code.duplicated().any():raise ValueError('FIDELITY_PROFILE_KEY_CONFLICT')
indexed=prof.set_index('ts_code');positions=indexed.index.get_indexer(df.ts_code)
if (positions<0).any():raise ValueError('FIDELITY_PROFILE_UNMATCHED_DO_NOT_USE_STEP7_FIRST_ROW_FALLBACK')
default_flags=pd.DataFrame({'ts_code':df.ts_code,'signal_date':df.signal_date})
mapping={'p54_repr_pb_quality_prob':('p54_emb_pb_qual',.5),'p54_repr_rev_r1r4_active_prob':('p54_emb_rev_r1r4',.5),
 'p54_repr_pb1_shallow_prob':('p54_emb_pb1',.5),'p54_repr_pb2_yellow_prob':('p54_emb_pb2',.5),'p54_repr_pb3_spring_prob':('p54_emb_pb3',.5),
 'p54_repr_exp_ret_t5_norm':('p54_emb_ret_t5',0.),'p54_repr_exp_mae_t10_norm':('p54_emb_mae_t10',0.),
 'p54_repr_exp_mfe_t10_norm':('p54_emb_mfe_t10',0.),'p54_repr_fail_risk_prob':('p54_emb_fail_risk',.35),
 'p54_repr_gbdt_stage_margin':('p54_emb_gbdt_margin_norm',0.),'p54_repr_ridge_projected_score':('y_teacher_ret_t5_pit',0.)}
for target,(src,default) in mapping.items():
    default_flags[target+'_source_missing']=df[src].isna();df[target]=df[src].fillna(default)
slope=['beta_jcb','beta_pb1','beta_pb2','beta_pb3','beta_b2','beta_vol_shrink','beta_j_wash','beta_yellow','beta_digested_bgb','beta_unabsorbed_bgb']
pre=.30*indexed[['w1_'+x for x in slope]].to_numpy(dtype=float)+.70*indexed[['w2_'+x for x in slope]].to_numpy(dtype=float)
post=.40*indexed[['w2_'+x for x in slope]].to_numpy(dtype=float)+.60*indexed[['pit2024_'+x for x in slope]].to_numpy(dtype=float)
after=pd.to_numeric(df.signal_date,errors='coerce').ge(20250101).to_numpy();B=np.where(after[:,None],post[positions],pre[positions])
for target,index in {'pers_eb_touch_white_win_edge':1,'pers_eb_touch_yellow_win_edge':2,'pers_eb_touch_keyk_bot_win_edge':3,
 'pers_eb_b1_win_edge':6,'pers_eb_b2_win_edge':4,'pers_eb_buildup_win_edge':0,'pers_eb_strong_weak_regime_spread':7}.items():df[target]=B[:,index]
for target,col in [('pers_eb_keyk_ret5_edge','alpha_i'),('pers_eb_big_green_fail_diff','gamma_fail')]:
    a=.30*indexed['w1_'+col].to_numpy(dtype=float)+.70*indexed['w2_'+col].to_numpy(dtype=float)
    b=.40*indexed['w2_'+col].to_numpy(dtype=float)+.60*indexed['pit2024_'+col].to_numpy(dtype=float)
    df[target]=np.where(after,b[positions],a[positions])
default_flags['pers_pb_depth_style_index_source_missing']=df.pb_depth_diff_from_habit.isna();df['pers_pb_depth_style_index']=df.pb_depth_diff_from_habit.fillna(0.)
if set(features)-set(df.columns):raise ValueError('FIDELITY_FEATURES_NOT_COMPLETE')
sample=pd.read_parquet(model/'sample_all_a_panel_2500.parquet',columns=keys+features)
j=sample.merge(df[keys+features],on=keys,validate='one_to_one',suffixes=('_sample','_reconstructed'),how='left',indicator=True)
if not j['_merge'].eq('both').all():raise ValueError('FIDELITY_SAMPLE_KEYS_MISSING')
diff={}
for c in features:
    a=pd.to_numeric(j[c+'_sample'],errors='coerce').to_numpy(dtype=float,na_value=np.nan);b=pd.to_numeric(j[c+'_reconstructed'],errors='coerce').to_numpy(dtype=float,na_value=np.nan)
    diff[c]=int((~np.isclose(a,b,rtol=0,atol=1e-12,equal_nan=True)).sum())
bad={k:v for k,v in diff.items() if v}
if bad:
    (root/'FIDELITY_87_FAILURE.json').write_text(json.dumps({'status':'SAMPLE_PARITY_FAILED','mismatch_counts':bad},ensure_ascii=False,indent=2)+'\n')
    raise ValueError('FIDELITY_87_SAMPLE_PARITY_FAILED:'+str(bad))
extras=['exit_date_t5','status_t5','ret_t5_pct','domain_source','gap_trading_days','zge_buypoint_type']
path=root/'inputs/FIDELITY_87_FEATURES.parquet';df[keys+extras+features].to_parquet(path,index=False,compression='zstd')
flagpath=root/'inputs/FIDELITY_SOURCE_DEFAULT_FLAGS.parquet';default_flags.to_parquet(flagpath,index=False,compression='zstd')
out={'status':'SOURCE_FAITHFUL_RECONSTRUCTION_SAMPLE_PARITY_PASS','rows':len(df),'feature_count':len(features),
 'sample_rows':len(j),'sample_key_matches':len(j),'per_feature_mismatch_counts':diff,'profile_unmatched':int((positions<0).sum()),
 'step7_source_sha256':r.sha(step),'second_base_sha256':r.sha(second),'profile_sha256':r.sha(profile),
 'first_panel_sha256_parent_readback':'ec10ffc05beec1ffee27cd3afe1c7e44a54cbeba1f705c6f6e633082a78c0a12',
 'feature_projection_path':str(path),'feature_projection_sha256':r.sha(path),'default_flags_path':str(flagpath),'default_flags_sha256':r.sha(flagpath),
 'source_default_counts':{c:int(default_flags[c].sum()) for c in default_flags if c.endswith('_source_missing')},
 'semantics':'SOURCE_FAITHFUL_EXPOSED_HISTORY; KNOWN_PRE2025_POSTERIOR_FUTURE_INFORMATION; NOT_PIT_CERTIFIED',
 'post_cutoff_rows':'RECONSTRUCTED_WITH_STEP7_TRANSFORMS_NOT_IN_ORIGINAL_FIT','fit':'NOT_RUN'}
(root/'FIDELITY_87_REPORT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:out[k] for k in ['status','rows','sample_rows','sample_key_matches','source_default_counts','feature_projection_sha256','default_flags_sha256','semantics']},ensure_ascii=False))
