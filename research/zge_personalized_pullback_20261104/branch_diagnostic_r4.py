"""Descriptive R4 anchor branch metrics and source-validity stratification."""
import json
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score,log_loss
from pipeline import OUT, atomic_json, sha

root=OUT/'r4/full';ev=pd.read_parquet(root/'events_features_labels.parquet');pred=pd.read_parquet(root/'predictions.parquet');valid=pd.read_parquet(root/'feature_validity_overlay.parquet')
events=ev[['ts_code','trade_date','event_group','anchor_key','anchor_wave','y10']].merge(
    valid[['ts_code','trade_date','source_prefix_tainted','source_event_basis']],on=['ts_code','trade_date'],validate='one_to_one')
events['branch']=np.select([events.anchor_key.fillna(False)&events.anchor_wave.fillna(False),events.anchor_key.fillna(False),events.anchor_wave.fillna(False)],['BOTH','KEY_ONLY','WAVE_ONLY'],default='INVALID')
assert not events.branch.eq('INVALID').any()
joined=pred.merge(events.drop(columns='y10'),on=['ts_code','trade_date','event_group'],validate='many_to_one',how='left')
assert not joined.branch.isna().any()
rows=[]
for fold in sorted(joined.fold.unique()):
 for branch in ['KEY_ONLY','WAVE_ONLY','BOTH']:
  for scope in ['ALL','SOURCE_PREFIX_UNCERTAIN','NO_KNOWN_INVALID_PREFIX']:
   z=joined[(joined.fold==fold)&(joined.branch==branch)]
   if scope=='SOURCE_PREFIX_UNCERTAIN':z=z[z.source_prefix_tainted]
   elif scope=='NO_KNOWN_INVALID_PREFIX':z=z[~z.source_prefix_tainted]
   y=z.y10; item={'fold':int(fold),'branch':branch,'source_scope':scope,'events':len(z),'stocks':int(z.ts_code.nunique()),'groups':int(z.event_group.nunique()),'positive_rate':None if not len(z) else float(y.mean())}
   for name in ['global','personal']:
    item[name+'_auc']=None if y.nunique()<2 else float(roc_auc_score(y,z[name+'_score']))
    item[name+'_logloss']=None if len(z)==0 else float(log_loss(y,z[name+'_score'],labels=[0,1]))
   rows.append(item)
comp={}
for branch,g in events.groupby('branch'):
 comp[str(branch)]={'events':len(g),'known_y10':int(g.y10.ge(0).sum()),'stocks':int(g.ts_code.nunique()),'groups':int(g.event_group.nunique()),'source_prefix_uncertain_events':int(g.source_prefix_tainted.sum())}
res={'status':'POSTHOC_DESCRIPTIVE_NOT_BRANCH_LIFT_ACCEPTANCE','source_events_sha256':sha(root/'events_features_labels.parquet'),
 'source_predictions_sha256':sha(root/'predictions.parquet'),'source_validity_sha256':sha(root/'feature_validity_overlay.parquet'),
 'candidate_composition':comp,'folds':rows,'warnings':['Event types are proxies, not established formula parity.','Repeated stock events and overlapping labels are dependent.','Posthoc strata have no multiple-testing or uncertainty correction.','Absence of known invalid OHLC does not certify source formula causality or PIT.']}
atomic_json(root/'ANCHOR_BRANCH_DIAGNOSTIC.json',res);pd.DataFrame(rows).to_csv(root/'ANCHOR_BRANCH_DIAGNOSTIC.csv',index=False)
print(json.dumps({'status':res['status'],'candidate_composition':comp,'rows':len(rows)},ensure_ascii=False))
