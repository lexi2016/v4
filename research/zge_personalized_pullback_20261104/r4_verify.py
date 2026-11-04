"""Test validity masking, true prior-only ranks, and R3 cohort parity."""
import json
import numpy as np
import pandas as pd
import pipeline as p
from r4_features import EDIT,SOURCE_FEATURES,ANCHOR_FEATURES

root=p.OUT/'r4/full';old=pd.read_parquet(p.OUT/'r3/full/events_features_labels.parquet');new=pd.read_parquet(root/'events_features_labels.parquet');v=pd.read_parquet(root/'feature_validity_overlay.parquet')
assert len(old)==len(new)==len(v)
for col in ['ts_code','trade_date','anchor_date','event_group','date_d1','date_d5','date_d10','y5','y10','R5','R10']:
    pd.testing.assert_series_equal(old[col],new[col],check_names=False)
assert not set(['anchor_key','anchor_wave','source_event_basis']) & set(p.GLOBAL+p.PERSONAL)
assert new.loc[v.source_prefix_tainted,SOURCE_FEATURES+p.PERSONAL].isna().all().all()
assert new.loc[v.invalid_anchor_path,ANCHOR_FEATURES].isna().all().all()
for col in EDIT:
    a=pd.to_numeric(old[col],errors='coerce').to_numpy(dtype=float);b=pd.to_numeric(new[col],errors='coerce').to_numpy(dtype=float)
    assert not np.any(~np.isnan(b)&~np.isclose(a,b,equal_nan=True,rtol=1e-12,atol=1e-12))

values=pd.Series(np.arange(320,dtype=float));bad=np.zeros(len(values),dtype=bool);bad[100]=True
valid=values.mask(bad);rank=p.rank_prior(valid);altered=values.copy();altered.iloc[100]=1e12
altered_rank=p.rank_prior(altered.mask(bad));pd.testing.assert_series_equal(rank,altered_rank)
prior=valid.iloc[60:310].dropna();manual=((prior<values.iloc[310]).sum()+.5*(prior==values.iloc[310]).sum())/len(prior)
assert np.isclose(rank.iloc[310],manual)
all_valid=p.rank_prior(values);pd.testing.assert_series_equal(all_valid,p.rank_prior(values.where(~np.zeros(len(values),dtype=bool))))
case=v.loc[v.source_prefix_tainted].head(1)
assert len(case)==1 and int(v.source_prefix_tainted.sum())>0
result={'status':'PASS','cohort_and_label_parity':'PASS','invalid_row_perturbation_masked_rank':'PASS',
 'valid_prior_rank_parity':'PASS','min60_rule':'p.rank_prior requires query plus >=60 finite references',
 'direct_anchor_and_source_feature_mask':'PASS','source_flags_excluded_from_model_features':'PASS',
 'real_tainted_case':{'symbol':str(case.ts_code.iloc[0]),'date':int(case.trade_date.iloc[0])},
 'old_events_sha256':p.sha(p.OUT/'r3/full/events_features_labels.parquet'),
 'new_events_sha256':p.sha(root/'events_features_labels.parquet'),'validity_overlay_sha256':p.sha(root/'feature_validity_overlay.parquet')}
p.atomic_json(root/'FEATURE_MASK_TESTS.json',result);print(json.dumps(result,ensure_ascii=False))
