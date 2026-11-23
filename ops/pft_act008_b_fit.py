"""ACT-008 fixed grouped S crossfit, twelve B fits, and prediction seal.

Fit reads TRAIN labels only. OOS truth and all post-D outcome bars are opened
by the separate score command only after every prediction/model hash verifies.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path: sys.path.insert(0,str(APP_ROOT))
from ops import pft_s_full_ashare as old
from ops import pft_s_full_ashare_fit as oldfit
from ops.pft_s_full_ashare_features import FEATURES as S_FEATURES
from ops.pft_act008_b_features import BASE_FEATURES, BRANCH_FEATURES, FULL_FEATURES, LANES
from ops.pft_act008_b import BATCH, FLAGS, write_json, _write_rows

FOLD_RULE="int(sha256('ACT-008|S-OOF|'+canonical_security_id).hexdigest()[:16],16)%5"


def fold_for(code):
    return int(hashlib.sha256(('ACT-008|S-OOF|'+code).encode()).hexdigest()[:16],16)%5


def matrix(path,columns):
    import pandas as pd
    import numpy as np
    frame=pd.read_csv(path)
    if list(frame.columns)!=list(columns) or frame.empty:
        raise oldfit.FitError('B_MATRIX_SCHEMA_OR_EMPTY:'+path.name)
    for name in columns:
        frame[name]=pd.to_numeric(frame[name],errors='raise')
    if np.isinf(frame.to_numpy(dtype=float)).any():
        raise oldfit.FitError('B_MATRIX_INFINITY:'+path.name)
    return frame


def check_file(root,name,expected):
    path=root/name
    if not path.is_file() or path.is_symlink() or not expected or old._sha_file(path)!=expected:
        raise oldfit.FitError('INPUT_SHA_MISMATCH:'+name)
    return path


def read_prepared(prepared_dir):
    manifest=old._read_json(prepared_dir/'manifest.json')
    if (manifest.get('batch')!=BATCH or manifest.get('flags')!=FLAGS or
        manifest.get('base_features')!=list(BASE_FEATURES) or
        manifest.get('s_features')!=list(S_FEATURES) or
        manifest.get('branch_features')!=[f'S_{n}' for n in BRANCH_FEATURES]):
        raise oldfit.FitError('PREPARED_B_IDENTITY_SCHEMA_MISMATCH')
    return manifest


def _loaded_inputs(prepared,manifest):
    import pandas as pd
    data={}
    for key in [f'{lane}_{split}' for lane in LANES for split in ('train','oos')]+['kb']:
        files=[f'{key}_{suffix}.csv' for suffix in ('identity','base','branches','s','gates')]
        if key.endswith('_train'): files.append(f'{key}_labels.csv')
        for name in files: check_file(prepared,name,manifest['outputs_sha256'].get(name))
        ids=oldfit._read_csv(prepared/f'{key}_identity.csv')
        base=matrix(prepared/f'{key}_base.csv',BASE_FEATURES)
        branches=matrix(prepared/f'{key}_branches.csv',[f'S_{n}' for n in BRANCH_FEATURES])
        s=matrix(prepared/f'{key}_s.csv',S_FEATURES)
        gates=oldfit._read_csv(prepared/f'{key}_gates.csv')
        if not len(ids)==len(base)==len(branches)==len(s)==len(gates):
            raise oldfit.FitError('PREPARED_B_ROW_ALIGNMENT:'+key)
        if key!='kb':
            lane,split=key.split('_')
            split=split.upper()
            if any(r['split']!=split or r['lane']!=lane for r in ids):
                raise oldfit.FitError('B_SPLIT_LANE_MISMATCH:'+key)
            codes=[r['canonical_security_id'] for r in ids]
            if len(codes)!=len(set(codes)) or len({r['episode_id'] for r in ids})!=len(ids):
                raise oldfit.FitError('B_DUPLICATE_SECURITY_OR_EPISODE:'+key)
            if any((split=='TRAIN' and r['D']>old.TRAIN_END) or (split=='OOS' and not old.OOS_START<=r['D']<=old.ASOF_DATE) for r in ids):
                raise oldfit.FitError('B_DATE_SPLIT_VIOLATION:'+key)
        item={'ids':ids,'base':base,'branches':branches,'s':s,'gates':gates}
        if key.endswith('_train'):
            labels=oldfit._read_csv(prepared/f'{key}_labels.csv')
            if len(labels)!=len(ids) or any(any(a.get(n)!=b.get(n) for n in ('episode_id','canonical_security_id','D','split','lane')) for a,b in zip(ids,labels)):
                raise oldfit.FitError('TRAIN_LABEL_IDENTITY_ALIGNMENT:'+key)
            y=[int(r['label']) for r in labels]
            if set(y)!={0,1}: raise oldfit.FitError('TRAIN_REQUIRES_TWO_KNOWN_CLASSES:'+key)
            item['y']=y
        data[key]=item
    return data


def s_train_inputs(act005_root,config,aliases):
    import pandas as pd
    p=act005_root/'prepared'
    for filename,key in [('train_manifest.csv','train_manifest_sha256'),('train_features.csv','train_features_sha256')]:
        check_file(p,filename,config[key])
    check_file(act005_root/'fit_v1','prediction_lock.json',config['source_prediction_lock_sha256'])
    rows=oldfit._read_csv(p/'train_manifest.csv')
    x=matrix(p/'train_features.csv',S_FEATURES)
    y=[{'TRUE':1,'FALSE':0}.get(r['label'].upper()) for r in rows]
    if len(rows)!=450 or len(x)!=450 or Counter(y)!={0:270,1:180}:
        raise oldfit.FitError('FROZEN_ACT005_S450_REQUIRED')
    codes=[aliases.get(r['canonical_security_id'],r['canonical_security_id']) for r in rows]
    if len(set(codes))!=450 or any(r['split']!='TRAIN' or r['D']>old.TRAIN_END for r in rows):
        raise oldfit.FitError('S450_CANONICAL_TRAIN_IDENTITY_INVALID')
    return rows,x,y,codes


def gated(probabilities,gates):
    import math
    values=[]
    for p,g in zip(probabilities,gates):
        try: gate=float(g['gate'])
        except (TypeError,ValueError): gate=math.nan
        if math.isnan(gate): values.append(math.nan)
        elif gate in (0.,1.): values.append(float(p)*gate)
        else: raise oldfit.FitError('S_FROZEN_GATE_NOT_BINARY_OR_UNKNOWN')
    return values


def fit_and_lock(*,prepared_dir:Path,artifact_root:Path,act005_root:Path,output_dir:Path):
    import numpy as np
    import pandas as pd
    import joblib
    prepared_dir,artifact_root,act005_root=(p.expanduser().resolve(strict=True) for p in (prepared_dir,artifact_root,act005_root))
    output_dir=output_dir.expanduser().absolute();stage=output_dir.with_name(output_dir.name+'.partial')
    if output_dir.exists() or stage.exists() or output_dir.is_symlink() or stage.is_symlink():
        raise oldfit.FitError('FIT_OUTPUT_EXISTS')
    if output_dir.parent.resolve(strict=True)!=artifact_root or prepared_dir.parent!=artifact_root:
        raise oldfit.FitError('FIT_OUTPUT_MUST_BE_PREPARED_SIBLING')
    manifest=read_prepared(prepared_dir)
    for name in ('S_FROZEN_V1_inference.json','scope_frozen.json','WRITER_SCOPE.md'):
        check_file(artifact_root,name,manifest['input_sha256'].get(name))
    config=old._read_json(artifact_root/'S_FROZEN_V1_inference.json')
    if config.get('primary_for_B')!='GEMINI_R2_FIXED_LR' or config.get('feature_columns')!=list(S_FEATURES) or config.get('model_configs')!=oldfit.MODEL_CONFIGS or config.get('threshold')!=.5 or config.get('G2_remove')!='G2_CLOSE_YELLOW_GE_35':
        raise oldfit.FitError('S_FROZEN_RECIPE_MISMATCH')
    frozen=old._validate_inputs(act005_root)
    if any(manifest['input_sha256'].get(name)!=sha for name,sha in frozen['input_sha256'].items()):
        raise oldfit.FitError('FROZEN_ACT005_SPLIT_IDENTITY_CHANGED')
    data=_loaded_inputs(prepared_dir,manifest)
    srows,sx,sy,scodes=s_train_inputs(act005_root,config,frozen['aliases'])
    train_codes={r['canonical_security_id'] for key,item in data.items() if key.endswith('_train') for r in item['ids']}
    oos_codes={r['canonical_security_id'] for key,item in data.items() if key.endswith('_oos') for r in item['ids']}
    if train_codes&oos_codes or set(scodes)&oos_codes:
        raise oldfit.FitError('CANONICAL_B_OR_S_TRAIN_OOS_OVERLAP')
    for code in train_codes|oos_codes:
        expected='TRAIN' if code in train_codes else 'OOS'
        if frozen['canonical_partition'].get(code)!=expected or code in frozen['excluded_canonical']:
            raise oldfit.FitError('B_NOT_IN_FROZEN_ALLOWED_COHORT:'+code)
    saved=config['weights']['GEMINI_R2_FIXED_LR'];saved_path=Path(saved['file'])
    check_file(saved_path.parent,saved_path.name,saved['sha256'])
    full_s=joblib.load(saved_path)
    if list(getattr(full_s,'feature_names_in_',[]))!=list(S_FEATURES):
        raise oldfit.FitError('S_SAVED_MODEL_FEATURE_ORDER_MISMATCH')
    stage.mkdir()
    progress={'status':'RUNNING','S_helper_fits':0,'B_fits':0,'completed_B_models':[],'flags':FLAGS}
    write_json(stage/'fit_progress.json',progress)
    fold_audit=[];s_audit=[]
    for item in data.values(): item['s_probability_raw']=np.full(len(item['ids']),np.nan)
    for fold in range(5):
        kept=[i for i,code in enumerate(scodes) if fold_for(code)!=fold]
        removed=[i for i in range(len(scodes)) if i not in set(kept)]
        model=oldfit._fixed_models()['GEMINI_R2_FIXED_LR']
        if set(sy[i] for i in kept)!={0,1}: raise oldfit.FitError('S_FOLD_TWO_CLASSES_REQUIRED')
        model.fit(sx.iloc[kept],[sy[i] for i in kept]);progress['S_helper_fits']+=1
        path=stage/f's_helper_fold{fold}.joblib';joblib.dump(model,path,compress=3)
        reloaded=joblib.load(path)
        query_codes=set()
        for key,item in data.items():
            if not key.endswith('_train'): continue
            indices=[i for i,r in enumerate(item['ids']) if fold_for(r['canonical_security_id'])==fold]
            if not indices: continue
            query_codes.update(item['ids'][i]['canonical_security_id'] for i in indices)
            probabilities=oldfit._probabilities(model,item['s'].iloc[indices])
            if not np.allclose(probabilities,oldfit._probabilities(reloaded,item['s'].iloc[indices]),rtol=0,atol=1e-15):
                raise oldfit.FitError('S_HELPER_SERIALIZATION_MISMATCH')
            item['s_probability_raw'][indices]=probabilities
        if query_codes&{scodes[i] for i in kept}: raise oldfit.FitError('S_OOF_QUERY_SECURITY_LEAKAGE')
        fold_audit.append({'fold':fold,'S_train_indices':kept,'S_train_canonical':[scodes[i] for i in kept],
                           'S_excluded_canonical':[scodes[i] for i in removed],'B_query_canonical':sorted(query_codes),
                           'model_file':path.name,'model_sha256':old._sha_file(path)})
        write_json(stage/'fit_progress.json',progress)
    for key,item in data.items():
        if not key.endswith('_train'):
            item['s_probability_raw']=np.asarray(oldfit._probabilities(full_s,item['s']))
        if not np.isfinite(item['s_probability_raw']).all(): raise oldfit.FitError('S_QUERY_PROBABILITY_NOT_FINITE:'+key)
        item['s_probability']=gated(item['s_probability_raw'],item['gates'])
        full=item['base'].copy();full['S_probability']=item['s_probability']
        full=pd.concat([full,item['branches']],axis=1)
        if list(full)!=list(FULL_FEATURES): raise oldfit.FitError('FULL_B_APPEND_SCHEMA_MISMATCH')
        item['full']=full
        _write_rows(stage/f'{key}_full.csv',full.to_dict('records'),FULL_FEATURES)
        for row,p,pg,g in zip(item['ids'],item['s_probability_raw'],item['s_probability'],item['gates']):
            s_audit.append({**row,'S_raw_probability':p,'S_probability':pg,'fold':fold_for(row['canonical_security_id']) if key.endswith('_train') else '',
                            'source':'GROUPED_S_OOF' if key.endswith('_train') else 'SAVED_ACT005_FULL_LR','gate_reason':g['gate_reason']})
    _write_rows(stage/'S_query_probabilities.csv',s_audit)
    write_json(stage/'S_crossfit_audit.json',{'fold_rule':FOLD_RULE,'folds':fold_audit,'S450_train_manifest_sha256':config['train_manifest_sha256'],'S450_train_features_sha256':config['train_features_sha256'],'saved_primary_sha256':saved['sha256']})
    predictions=[];models={}
    for lane in LANES:
        train=data[f'{lane}_train']
        for arm,field,features in [('BASELINE_B','base',BASE_FEATURES),('FULL_B','full',FULL_FEATURES)]:
            for name,model in oldfit._fixed_models().items():
                model_key=f'{lane}__{arm}__{name}'
                model.fit(train[field],train['y']);progress['B_fits']+=1
                path=stage/f'{model_key}.joblib';joblib.dump(model,path,compress=3)
                reloaded=joblib.load(path)
                for exam,item in [('OOS',data[f'{lane}_oos']),('EXPOSED_KB25',data['kb'])]:
                    probabilities=oldfit._probabilities(model,item[field])
                    if not np.allclose(probabilities,oldfit._probabilities(reloaded,item[field]),rtol=0,atol=1e-15):
                        raise oldfit.FitError('B_MODEL_SERIALIZATION_MISMATCH:'+model_key)
                    for row,p in zip(item['ids'],probabilities):
                        predictions.append({**row,'exam':exam,'lane':lane,'arm':arm,'estimator':name,'probability':p,'decision':int(p>=.5)})
                models[path.name]=old._sha_file(path)
                progress['completed_B_models'].append(model_key);write_json(stage/'fit_progress.json',progress)
    if progress['B_fits']!=12 or progress['S_helper_fits']!=5: raise oldfit.FitError('ACTUAL_FIT_COUNT_MISMATCH')
    _write_rows(stage/'predictions.csv',predictions)
    sealed={p.name:old._sha_file(p) for p in stage.iterdir() if p.is_file() and p.name!='fit_progress.json'}
    lock={'schema':'pft_act008_prediction_lock.v1','batch':BATCH,'flags':FLAGS,
          'locked_at_utc':datetime.now(timezone.utc).isoformat(),
          'prepared_manifest_sha256':old._sha_file(prepared_dir/'manifest.json'),
          'prepared_inputs_sha256':{n:sha for n,sha in manifest['outputs_sha256'].items() if not n.endswith('_labels.csv') or '_train_' in n},
          'sealed_outputs_sha256':sealed,'B_model_sha256':models,'model_configs':oldfit.MODEL_CONFIGS,
          'base_features':list(BASE_FEATURES),'full_features':list(FULL_FEATURES),'threshold':.5,
          'S_fold_rule':FOLD_RULE,'S_primary_saved_model_sha256':saved['sha256'],
          'prepared_code_sha256':manifest.get('code_sha256',{}),
          'code_sha256':{p.name:old._sha_file(p) for p in sorted((APP_ROOT/'ops').glob('pft_act008_b*.py'))},
          'selected_evidence_compatibility':({'file':'selected_window_evidence_check.json','sha256':old._sha_file(artifact_root/'selected_window_evidence_check.json')}
              if (artifact_root/'selected_window_evidence_check.json').is_file() else None),
          'actual_fit_counts':{'S_helper':5,'B':12},'OOS_truth_read':False,'post_D_outcomes_read':False}
    write_json(stage/'prediction_lock.json',lock)
    progress['status']='LOCKED';progress['prediction_lock_sha256']=old._sha_file(stage/'prediction_lock.json')
    write_json(stage/'fit_progress.json',progress)
    stage.replace(output_dir)
    return progress


def verify_lock(prepared_dir,fit_dir):
    lock=old._read_json(fit_dir/'prediction_lock.json')
    if lock.get('schema')!='pft_act008_prediction_lock.v1' or lock.get('batch')!=BATCH or lock.get('flags')!=FLAGS or lock.get('actual_fit_counts')!={'S_helper':5,'B':12} or lock.get('threshold')!=.5:
        raise oldfit.FitError('PREDICTION_LOCK_IDENTITY_INVALID')
    check_file(prepared_dir,'manifest.json',lock['prepared_manifest_sha256'])
    for name,sha in lock['sealed_outputs_sha256'].items(): check_file(fit_dir,name,sha)
    for name,sha in lock['prepared_inputs_sha256'].items(): check_file(prepared_dir,name,sha)
    for name,sha in lock.get('code_sha256',{}).items():check_file(APP_ROOT/'ops',name,sha)
    return lock


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['fit'])
    for name in ('prepared-dir','artifact-root','act005-root','output-dir'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    try:result=fit_and_lock(prepared_dir=args.prepared_dir,artifact_root=args.artifact_root,act005_root=args.act005_root,output_dir=args.output_dir)
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error':str(exc)}),file=sys.stderr);return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
