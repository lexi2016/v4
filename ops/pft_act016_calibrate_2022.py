"""Replay ACT015's established D-only inference on 2022 prefixes for q80 calibration."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
from time import monotonic
import joblib
import pandas as pd

from ops import pft_act015_common as c, pft_act015_fit as fit, pft_act015_project as project
from ops import pft_s_first_baseline as baseline, research_panel_logical as reader

def main():
    arg=argparse.ArgumentParser()
    for name in ('artifact','fit','data','act005'):
        arg.add_argument('--'+name,type=Path,required=True)
    arg.add_argument('--workers',type=int,default=16)
    arg.add_argument('--canary',action='store_true')
    x=arg.parse_args()
    start=monotonic()
    m=c.read_manifest(x.fit,'fit_manifest.json')
    assert m['actual_successful_fit_calls']==80
    fold={held:x.fit/f'models/2023_held{held}' for held in (0,1)}
    main_s={held:joblib.load(path/'S_MAIN.joblib') for held,path in fold.items()}
    models={held:{(lane,role):joblib.load(path/(lane+('_B.joblib' if role=='B' else '_RANK_H5.joblib')))
                   for lane in c.LANES for role in ('B','R')} for held,path in fold.items()}
    keep=['episode_id','D','canonical_security_id','lane','outer','held_outer','S_prob_gated','B_probability','rank_score','hard_eligible']
    history=[s for s in m['sessions'] if s<'20230101']
    assert len(history)==242
    out=[]
    rows=0
    seen=set()
    with baseline.bind_current_panels(x.data) as (path, source, recheck):
        c.assert_source(source,c.old._validate_inputs(x.act005))
        assert source['identity']==m['source']['identity']
        aliases,groups,crosswalk=c.observed_universe(path,reader)
        if x.canary:
            groups={code:groups[code] for code in ('600519.SH','601019.SH','002693.SZ','300750.SZ','920510.BJ','000001.SZ')}
        schema=reader.parquet.read_schema(path)
        mapping,_=c.panel_columns(schema)
        names=c.old._schema_names(schema)
        mapping.update({name:names[name] for name in ('limit_up_approx','limit_down_approx')})
        with ProcessPoolExecutor(max_workers=x.workers,initializer=project.worker_init) as pool:
            for cohort,symbols in enumerate(c.cohorts(groups,384)):
                frame=c.read_cohort(path,schema,mapping,symbols,reader,lo='20220101',hi='20221231')
                rows+=len(frame)
                frame['canonical_security_id']=frame.ts_code.map(aliases)
                tasks=((code,part.drop(columns='canonical_security_id'),crosswalk,history)
                       for code,part in frame.groupby('canonical_security_id',sort=True))
                nat=[]
                for natural,_,stats in pool.map(project.project_security,tasks,chunksize=4):
                    seen.add(stats['canonical_security_id'])
                    if len(natural):
                        nat.append(natural)
                if nat:
                    projected=pd.concat(nat,ignore_index=True)
                    for held in (0,1):
                        # infer_frame's year parameter also filters D. We use 2022 D on actual 2023 held-side weights.
                        y=fit.infer_frame(projected,2022,held,main_s[held],models[held])
                        y=y.loc[y.hard_eligible & y.lane.isin(['B1','B2']),keep]
                        if len(y):out.append(y)
                print(json.dumps({'stage':'2022_PRIOR_ONLY','cohort':cohort,'codes_with_2022_bars':len(seen),
                                  'rows_source':rows,'elapsed_sec':round(monotonic()-start,1)}),flush=True)
        recheck()
    f=pd.concat(out,ignore_index=True).sort_values(['D','canonical_security_id','lane']).reset_index(drop=True)
    assert f.D.str.startswith('2022').all() and f.outer.eq(f.held_outer).all() and not f.episode_id.duplicated().any()
    f['model_year']=2023
    f['calibration_kind']='2022_ISSUER_OUT_OF_FOLD_PRIOR_ONLY'
    fit_sha=c.old._sha_file(x.fit/'fit_manifest.json')
    dep={n:sha for n,sha in m['outputs_sha256'].items() if n.startswith('models/2023_') and n.endswith('.joblib') and 'S_INNER' not in n}
    tag='_canary' if x.canary else ''
    fpath=x.artifact/f'q80_starter_2022{tag}.parquet'
    assert not fpath.exists()
    f.to_parquet(fpath,index=False,compression='zstd')
    receipt={'batch':'ACT-016','fit_calls':0,'date_min':f.D.min(),'date_max':f.D.max(),'sha256':c.old._sha_file(fpath),
             'rows':len(f),'fit_manifest_sha256':fit_sha,'source':source,'fit_models_sha256':dep,
             'calibration_model_year':2023,'date_scope':['20220101','20221231'],
             'issuer_held_excluded_from_all_scoring_weights':True,'chronological_2022_oos':False,
             'same_2022_model_training_period_but_other_issuers':True,
             'archive_decision_inputs_only':True,'source_rows_scanned':rows,'codes':len(seen),'workers':x.workers,
             'observations_by_lane':f.lane.value_counts().to_dict(),
             'q80_by_lane':f.groupby('lane').rank_score.quantile(.8).to_dict(),
             'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'mode':'CANARY' if x.canary else 'FULL'}
    c.write_json(x.artifact/f'q80_starter_2022{tag}_manifest.json',receipt)
    print(json.dumps(receipt,sort_keys=True),flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
