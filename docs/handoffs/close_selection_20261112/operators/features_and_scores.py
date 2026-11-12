"""One-batch orchestration of frozen feature/date adapters; no signal inventions."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,hashlib,importlib.util,json,pathlib,subprocess,sys,time
import numpy as np,pandas as pd
N=pathlib.Path(__file__).resolve().parents[1];ADAPTER=pathlib.Path('/Users/lexi/Desktop/学习/Z哥方法论/SELECTION_D20261112_WORKTREE/05_EXPERIMENTS/SELECTION_D20261112')
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):
 p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
 a=argparse.ArgumentParser();a.add_argument('phase',choices=['canary','remaining']);args=a.parse_args();t=time.perf_counter()
 old=json.loads((N/'MODEL_ENTRY_INSPECTION.json').read_text());sources=old['sources'];binding=json.loads((N/'SOURCE_ADAPTER_BINDING.json').read_text())
 for ref in list(sources.values())+list(binding['files'].values()):assert sha(ref['path'])==ref['sha256'],'SOURCE_DRIFT'
 r=json.loads((N/'validation'/(args.phase.upper()+'_PROJECTION.json')).read_text());prefix=N/'data'/(args.phase.upper()+'_PREFIX.parquet');assert sha(prefix)==r['projection_sha256']
 spec=importlib.util.spec_from_file_location('same_feature_definitions_d12',ADAPTER/'features_d12.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 frame=pd.read_parquet(prefix);features=m.build(frame,r['keys'],sources);cols=json.loads(pathlib.Path(sources['old_model_freeze']['path']).read_text())['feature_columns']['D']
 if args.phase=='canary':
  # Actual D-after input perturbation must not change any D12 feature/status.
  future=frame.sort_values('trade_date').groupby('ts_code',sort=False).tail(1).copy();future['trade_date']='20261113'
  for col in ('open','high','low','close','volume'):future[col]=pd.to_numeric(future[col])*100
  after=m.build(pd.concat([frame,future],ignore_index=True),r['keys'],sources)
  assert np.array_equal(features[cols].to_numpy(dtype=float),after[cols].to_numpy(dtype=float),equal_nan=True)
  assert features[['sample_id','feature_status','unknown_reasons']].equals(after[['sample_id','feature_status','unknown_reasons']])
  save(N/'validation/FUTURE_PREFIX_MASK_CANARY.json',dict(status='PASS_ACTUAL_APPENDED_AND_PERTURBED_D13_IGNORED',symbols=r['keys'],numeric_feature_values=len(features)*len(cols),fit_count=0,predictions_added=0))
 path=N/'data'/(args.phase.upper()+'_FEATURES_32.csv');assert not path.exists(),'FEATURES_EXIST_NO_RECOMPUTE';features.to_csv(path,index=False,float_format='%.17g')
 replay=pd.read_csv(path,float_precision='round_trip');assert np.array_equal(features[cols].to_numpy(dtype=float),replay[cols].to_numpy(dtype=float),equal_nan=True)
 freeze=dict(status='FROZEN_BEFORE_D12_ROLE_SCORE',source_date='2026-11-12',phase=args.phase,source_files=sources,engine_run_freeze_sha256=sha(N/'RUN_FREEZE.json'),adapter_binding_sha256=sha(N/'SOURCE_ADAPTER_BINDING.json'),features=dict(path=str(path),sha256=sha(path)),fit_allowed=False,model_semantics='old development D folds displayed as research roles; NO_BREAKTHROUGH/no final/calibration retained')
 fp=N/'validation'/(args.phase.upper()+'_MODEL_INPUT_FREEZE.json');save(fp,freeze);env=dict(os.environ,D12_RESEARCH_RUN_FREEZE_SHA256=sha(fp),D12_RESEARCH_FEATURES_SHA256=sha(path),PYTHONDONTWRITEBYTECODE='1')
 output=N/'outputs'/(args.phase.upper()+'_ROLE_SCORES_LONG.csv');output.parent.mkdir(exist_ok=True)
 command=[sys.executable,'-B',str(ADAPTER/'infer_d12.py'),'--features',str(path),'--run-freeze',str(fp),'--prefit',sources['old_model_freeze']['path'],'--fold1',sources['old_D_fold_1']['path'],'--fold2',sources['old_D_fold_2']['path'],'--fold3',sources['old_D_fold_3']['path'],'--output',str(output)]
 run=subprocess.run(command,env=env,capture_output=True,text=True);save(N/'validation'/(args.phase.upper()+'_INFERENCE_COMMAND.json'),dict(command=command,returncode=run.returncode,stdout=run.stdout,stderr=run.stderr,freeze_sha256=sha(fp)))
 if run.returncode:raise RuntimeError(run.stderr)
 result=json.loads(run.stdout.strip());assert result['fit_attempts']==0 and result['rows']==len(features)
 receipt=dict(status='PASS_D12_FEATURE_AND_ZERO_FIT_INFERENCE',phase=args.phase,source_generation=r['source_generation'],rows=len(features),feature_status=features.feature_status.value_counts().to_dict(),feature_sha256=sha(path),output_sha256=sha(output),inference=result,wall_seconds=time.perf_counter()-t,fit_attempts=0)
 save(N/'validation'/(args.phase.upper()+'_FEATURE_AND_SCORE_PASS.json'),receipt)
 if args.phase=='remaining':
  candidates=pd.read_csv(N/'data/CANDIDATES.csv',dtype=str);keys=set(candidates.symbol)
  allfeatures=pd.concat([pd.read_csv(N/'data/CANARY_FEATURES_32.csv',dtype={'security_code':str},float_precision='round_trip'),features],ignore_index=True);allfeatures=allfeatures[allfeatures.security_code.isin(keys)].sort_values('security_code');assert len(allfeatures)==len(keys) and allfeatures.security_code.nunique()==len(keys)
  allfeatures.to_csv(N/'data/D12_ALL_CANDIDATE_FEATURES_32.csv',index=False,float_format='%.17g')
  scores=pd.concat([pd.read_csv(N/'outputs/CANARY_ROLE_SCORES_LONG.csv',dtype={'security_code':str},float_precision='round_trip'),pd.read_csv(output,dtype={'security_code':str},float_precision='round_trip')],ignore_index=True);scores=scores[scores.security_code.isin(keys)].sort_values(['security_code','role']);assert len(scores)==len(keys)*4 and not scores.duplicated(['security_code','role']).any()
  scores.to_csv(N/'outputs/D12_ALL_ROLE_SCORES_LONG.csv',index=False,float_format='%.17g');wide=[]
  for code,group in scores.groupby('security_code',sort=True):
   row=dict(security_code=code)
   for role in group.itertuples():
    for field in ('fold_1','fold_2','fold_3','mean','min','max','threshold_0_5_disagreement'):row[role.role+'_'+field]=getattr(role,field)
   wide.append(row)
  pd.DataFrame(wide).to_csv(N/'outputs/D12_ALL_ROLE_SCORES_WIDE.csv',index=False,float_format='%.17g')
  save(N/'NUMERIC_COMPLETION.json',dict(status='FULL_CANDIDATE_ZERO_FIT_NUMERIC_COMPLETE',candidates=len(keys),role_rows=len(scores),eligible_candidate_count=int(allfeatures.feature_status.isin(['ELIGIBLE_32','ELIGIBLE_ZERO_RANGE_IMPUTER']).sum()),unknown_candidate_count=int((~allfeatures.feature_status.isin(['ELIGIBLE_32','ELIGIBLE_ZERO_RANGE_IMPUTER'])).sum()),feature_sha256=sha(N/'data/D12_ALL_CANDIDATE_FEATURES_32.csv'),scores_sha256=sha(N/'outputs/D12_ALL_ROLE_SCORES_LONG.csv'),canary_scoring_symbols=json.loads((N/'validation/CANARY_PROJECTION.json').read_text())['keys'],all_scored_dates=['2026-11-12'],NEW_FIT_COUNT=0))
 print(json.dumps(receipt),flush=True)
if __name__=='__main__':main()
