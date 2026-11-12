#!/usr/bin/env python3
"""Read-only D12 inference, supplied feature/contract/three-weight paths, never fit."""
import argparse,hashlib,json,os
from pathlib import Path
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
import joblib,numpy as np,pandas as pd,sklearn
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
ROLES=('activity','reversal_key','buy_point','risk');ATTEMPTS=[]
def forbidden(*args,**kwargs):
 ATTEMPTS.append('fit');raise RuntimeError('STOP all fitting is forbidden')
for cls in (SimpleImputer,StandardScaler,LogisticRegression,Pipeline):
 for method in ('fit','fit_transform','fit_predict','partial_fit'):
  if hasattr(cls,method):setattr(cls,method,forbidden)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(description=__doc__)
 for name in ('features','run-freeze','prefit','fold1','fold2','fold3','output'):a.add_argument('--'+name,required=True)
 args=a.parse_args();out=Path(args.output)
 if out.exists():raise RuntimeError('STOP output exists')
 if sklearn.__version__!='1.8.0':raise RuntimeError('STOP model requires sklearn 1.8.0')
 if sha(args.run_freeze)!=os.environ['D12_RESEARCH_RUN_FREEZE_SHA256']:raise RuntimeError('STOP wrong run freeze')
 cfg=json.loads(Path(args.run_freeze).read_text());sources=cfg['source_files'];paths={'old_model_freeze':args.prefit,'old_D_fold_1':args.fold1,'old_D_fold_2':args.fold2,'old_D_fold_3':args.fold3}
 before={name:sha(path) for name,path in paths.items()}
 if any(before[name]!=sources[name]['sha256'] for name in paths):raise RuntimeError('STOP old contract/model hash mismatch')
 old=json.loads(Path(args.prefit).read_text());cols=old['feature_columns']['D']
 if len(cols)!=32 or len(set(cols))!=32 or set(old['active_roles'])!=set(ROLES):raise RuntimeError('STOP old contract features/roles')
 if sha(args.features)!=os.environ['D12_RESEARCH_FEATURES_SHA256']:raise RuntimeError('STOP feature content hash mismatch')
 data=pd.read_csv(args.features,dtype={'sample_id':str,'security_code':str,'trade_date':str},float_precision='round_trip')
 if data.sample_id.duplicated().any() or set(data.trade_date)!={'2026-11-12'} or not (data.sample_id==data.security_code+'|2026-11-12').all():raise RuntimeError('STOP only distinct actual D12 sample IDs allowed')
 valid=('ELIGIBLE_32','ELIGIBLE_ZERO_RANGE_IMPUTER');eligible=data[data.feature_status.isin(valid)];x=eligible[cols].to_numpy(dtype=float);allow={'close_in_bar','upper_wick_in_bar','lower_wick_in_bar'}
 if np.isinf(x).any():raise RuntimeError('STOP infinite features')
 for i,r in enumerate(eligible.itertuples(index=False)):
  nulls={cols[j] for j in np.flatnonzero(np.isnan(x[i]))}
  if (r.feature_status=='ELIGIBLE_32' and nulls) or (r.feature_status=='ELIGIBLE_ZERO_RANGE_IMPUTER' and nulls!=allow):raise RuntimeError('STOP missing block or unexplained NaN')
 by_id={sid:{} for sid in eligible.sample_id}
 for i in (1,2,3):
  model=joblib.load(paths['old_D_fold_'+str(i)])
  if set(model)!=set(ROLES):raise RuntimeError('STOP role mismatch')
  for role in ROLES:
   h=model[role]
   if h['columns']!=cols or any(getattr(h[k],'n_features_in_',None)!=32 for k in ('imputer','scaler','estimator')) or list(h['estimator'].classes_)!=[0,1]:raise RuntimeError('STOP head/preprocess mismatch')
   if len(eligible):
    z=h['imputer'].transform(x)
    if not np.isfinite(z).all():raise RuntimeError('STOP invalid imputed data')
    pred=h['estimator'].predict_proba(h['scaler'].transform(z))[:,1]
    if not np.isfinite(pred).all():raise RuntimeError('STOP invalid prediction')
    for sid,prediction in zip(eligible.sample_id,pred):by_id[sid].setdefault(role,[]).append(float(prediction))
 rows=[]
 for r in data.itertuples(index=False):
  for role in ROLES:
   row={'sample_id':r.sample_id,'security_code':r.security_code,'trade_date':r.trade_date,'role':role,'feature_status':r.feature_status,'fold_1':None,'fold_2':None,'fold_3':None,'mean':None,'min':None,'max':None,'threshold_0_5_disagreement':None}
   if r.feature_status in valid:
    values=by_id[r.sample_id][role]
    if len(values)!=3:raise RuntimeError('STOP incomplete folds')
    row.update({'fold_1':values[0],'fold_2':values[1],'fold_3':values[2],'mean':sum(values)/3,'min':min(values),'max':max(values),'threshold_0_5_disagreement':min(values)<.5<=max(values)})
   rows.append(row)
 if {name:sha(path) for name,path in paths.items()}!=before or ATTEMPTS:raise RuntimeError('STOP model mutated or fit attempted')
 with out.open('x',encoding='utf-8',newline='') as f:pd.DataFrame(rows).to_csv(f,index=False,float_format='%.17g')
 print(json.dumps({'status':'NO_FIT_D12_INFERENCE','rows':len(data),'eligible':len(eligible),'role_rows':len(rows),'features_sha256':sha(args.features),'output_sha256':sha(out),'model_sha256':before,'fit_attempts':len(ATTEMPTS),'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False},ensure_ascii=False))
if __name__=='__main__':main()
