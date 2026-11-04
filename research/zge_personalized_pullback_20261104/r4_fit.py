"""Refit feature-dependent R3 models on the same event/label cohort with R4 masks."""
from pathlib import Path
import os
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score,log_loss,brier_score_loss,accuracy_score,average_precision_score
from threadpoolctl import threadpool_limits
import pipeline as p

ROOT=p.OUT;DEST=ROOT/'r4/full';CONTRACT=ROOT/'EXPERIMENT_CONTRACT_R4.json'
ev=pd.read_parquet(DEST/'events_features_labels.parquet');sessions=pd.read_parquet(DEST/'observed_a_sessions.parquet').trade_date.to_numpy()
oldpred=pd.read_parquet(ROOT/'r3/full/predictions.parquet');oldmetrics=__import__('json').loads((ROOT/'r3/full/METRICS.json').read_text())
folds=[];predictions=[]
def same_params(a,b):
    if a.keys()!=b.keys():return False
    for key in a:
        x,y=a[key],b[key]
        if isinstance(x,float) and isinstance(y,float) and np.isnan(x) and np.isnan(y):continue
        if x!=y:return False
    return True

for fold,(cut,end) in enumerate(zip(p.CONTRACT['split']['training_cuts'],p.CONTRACT['split']['test_end']),1):
    tr,te,split=p.split_masks(ev,sessions,cut,end);train=ev.loc[tr];test=ev.loc[te];y=train.y10.astype(int);actual=test.y10.astype(int)
    prior=oldmetrics['folds'][fold-1]
    assert (len(train),len(test))==(prior['train_count'],prior['test_count'])
    assert float(y.mean())==prior['train_positive_rate'] and float(actual.mean())==prior['test_positive_rate']
    old=oldpred.loc[oldpred.fold.eq(fold)].reset_index(drop=True)
    pd.testing.assert_frame_equal(test[['ts_code','trade_date','anchor_date','event_group','date_d10','y10','R10']].reset_index(drop=True),
        old[['ts_code','trade_date','anchor_date','event_group','date_d10','y10','R10']],check_exact=True)
    def tree():return HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=15,learning_rate=.06,min_samples_leaf=30,l2_regularization=1.0,early_stopping=False,random_state=42)
    models={'global':(tree(),p.GLOBAL),'personal':(tree(),p.GLOBAL+p.PERSONAL),
      'logistic':(make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),LogisticRegression(max_iter=400,random_state=42)),p.GLOBAL)}
    row={'fold':fold,**split,'train_count':len(train),'test_count':len(test),'train_positive_rate':float(y.mean()),'test_positive_rate':float(actual.mean()),'models':{}}
    pred=test[['ts_code','trade_date','anchor_date','event_group','date_d10','y10','R10']].copy()
    for name,(est,cols) in models.items():
        prior_model=joblib.load(ROOT/f'r3/full/fold{fold}_{name}.joblib')
        assert prior_model['feature_columns']==cols
        if name in ('global','personal'):assert same_params(prior_model['estimator'].get_params(),est.get_params())
        else:
            for step in ('simpleimputer','standardscaler','logisticregression'):
                assert same_params(prior_model['estimator'].named_steps[step].get_params(),est.named_steps[step].get_params())
        mp=DEST/f'fold{fold}_{name}.joblib';reused=mp.exists()
        if reused:
            saved=joblib.load(mp);assert saved['feature_columns']==cols and saved['contract_sha256']==p.sha(CONTRACT)
            est=saved['estimator']
            if name in ('global','personal'):assert same_params(prior_model['estimator'].get_params(),est.get_params())
            else:
                for step in ('simpleimputer','standardscaler','logisticregression'):
                    assert same_params(prior_model['estimator'].named_steps[step].get_params(),est.named_steps[step].get_params())
        else:
            with threadpool_limits(limits=12):est.fit(train[cols].astype(float),y)
            joblib.dump({'estimator':est,'feature_columns':cols,'contract_sha256':p.sha(CONTRACT),'score_is_calibrated':False},mp,compress=3)
        with threadpool_limits(limits=12):score=est.predict_proba(test[cols].astype(float))[:,1]
        sample=test[cols].head(20).copy();sp=DEST/f'fold{fold}_{name}_parity_input.parquet';pp=DEST/f"fold{fold}_{name}_parity_output{'_resume' if reused else ''}.npy"
        if sp.exists():pd.testing.assert_frame_equal(pd.read_parquet(sp),sample.reset_index(drop=True),check_dtype=False)
        else:p.write_parquet_atomic(sample,sp)
        p.model_predict_subprocess(mp,sp,pp)
        if not np.allclose(np.load(pp),est.predict_proba(sample.astype(float))[:,1],rtol=1e-12,atol=1e-12):raise AssertionError('R4_MODEL_PARITY:'+name)
        pred[name+'_score']=score
        row['models'][name]={'ROC_AUC':float(roc_auc_score(actual,score)),'log_loss':float(log_loss(actual,score,labels=[0,1])),
          'Brier_uncalibrated_score':float(brier_score_loss(actual,score)),'accuracy_at_0.5':float(accuracy_score(actual,score>=.5)),
          'average_precision':float(average_precision_score(actual,score)),'model_path':str(mp),'model_sha256':p.sha(mp),
          'fresh_process_parity':'PASS','origin':'R4_REUSED_AFTER_ASSERT_FAILURE' if reused else 'R4_REFIT_FEATURE_MASKED'}
    # Majority depends only on the identical y cohort; preserve the exact R3 weights and scores.
    oldmodel=ROOT/f'r3/full/fold{fold}_majority.joblib';newmodel=DEST/f'fold{fold}_majority.joblib'
    if not newmodel.exists():os.link(oldmodel,newmodel)
    assert p.sha(oldmodel)==p.sha(newmodel)
    majority=joblib.load(oldmodel)['estimator'];score=majority.predict_proba(test[p.GLOBAL].astype(float))[:,1]
    assert np.array_equal(score,old.majority_score.to_numpy())
    pred['majority_score']=score;row['models']['majority']={**prior['models']['majority'],'model_path':str(newmodel),
      'origin':'REUSED_IDENTICAL_INPUT','label_cohort_identity':'PASS','model_sha256':p.sha(newmodel)}
    row['paired_auc_difference']=row['models']['personal']['ROC_AUC']-row['models']['global']['ROC_AUC']
    row['paired_log_loss_difference']=row['models']['personal']['log_loss']-row['models']['global']['log_loss']
    folds.append(row);pred['fold']=fold;predictions.append(pred)
    p.atomic_json(DEST/'FIT_CHECKPOINT.json',{'completed_folds':folds,'status':'IN_PROGRESS'});print(__import__('json').dumps(row),flush=True)
allpred=pd.concat(predictions,ignore_index=True);p.write_parquet_atomic(allpred,DEST/'predictions.parquet')
p.atomic_json(DEST/'METRICS.json',{'folds':folds,'predictions_sha256':p.sha(DEST/'predictions.parquet'),
 'score_semantics':'UNCALIBRATED_MODEL_SCORES','decision':'DIRECTION_ONLY','sealed':'NOT_SEALED_ALL_EXPOSED',
 'is_strategy_or_tradability_validation':False,'majority':'REUSED_IDENTICAL_INPUT'})
p.atomic_json(DEST/'FIT_CHECKPOINT.json',{'completed_folds':folds,'status':'COMPLETE'})
