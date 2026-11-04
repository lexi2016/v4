"""Posthoc descriptive decomposition by frozen, possibly overlapping anchor types."""
import json
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score,log_loss
from pipeline import OUT, atomic_json, sha

root=OUT/'r3/full';ev=pd.read_parquet(root/'events_features_labels.parquet');pred=pd.read_parquet(root/'predictions.parquet')
events=ev[['ts_code','trade_date','event_group','anchor_key','anchor_wave','y10']].copy()
assert not events.duplicated(['ts_code','trade_date']).any()
events['branch']=np.select([events.anchor_key.fillna(False)&events.anchor_wave.fillna(False),events.anchor_key.fillna(False),events.anchor_wave.fillna(False)],['BOTH','KEY_ONLY','WAVE_ONLY'],default='INVALID')
assert not events.branch.eq('INVALID').any()
joined=pred.merge(events.drop(columns='y10'),on=['ts_code','trade_date','event_group'],validate='many_to_one',how='left')
assert not joined.branch.isna().any()
descriptive=[]
for fold in sorted(joined.fold.unique()):
 for branch in ['KEY_ONLY','WAVE_ONLY','BOTH']:
  a=joined[(joined.fold==fold)&(joined.branch==branch)];y=a.y10
  row={'fold':int(fold),'branch':branch,'events':len(a),'unique_stocks':int(a.ts_code.nunique()),'unique_groups':int(a.event_group.nunique()),'positive_rate':None if not len(a) else float(y.mean())}
  for name in ['global','personal']:
   row[name+'_auc']=None if y.nunique()<2 else float(roc_auc_score(y,a[name+'_score']))
   row[name+'_logloss']=None if len(a)==0 else float(log_loss(y,a[name+'_score'],labels=[0,1]))
  descriptive.append(row)
comp={}
for branch,g in events.groupby('branch'):
 comp[str(branch)]={'event_count':len(g),'known_y10':int(g.y10.ge(0).sum()),'stock_count':int(g.ts_code.nunique()),'group_count':int(g.event_group.nunique())}
res={'status':'POSTHOC_DESCRIPTIVE_NOT_PRESPECIFIED_NOT_BRANCH_LIFT_ACCEPTANCE','source_features_sha256':sha(root/'events_features_labels.parquet'),
 'source_predictions_sha256':sha(root/'predictions.parquet'),'branch_rules':'KEY_ONLY, WAVE_ONLY, BOTH; mutually exclusive descriptive partitions of the OR anchor proxy',
 'candidate_composition':comp,'folds':descriptive,'warnings':['Repeated stock events and overlapping horizons are dependent.','No multiple-comparison or uncertainty correction.','Source indicator parity and causality not certified; lower-level past-only perturbation cannot prove upstream causality.']}
atomic_json(root/'ANCHOR_BRANCH_DIAGNOSTIC.json',res);pd.DataFrame(descriptive).to_csv(root/'ANCHOR_BRANCH_DIAGNOSTIC.csv',index=False)
print(json.dumps(res,ensure_ascii=False))
