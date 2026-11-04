"""Conservative invalid-price-prefix mask over the cached R3 event cohort.

Only targeted symbol row groups are read and only their price/feature columns.
Once an OHLC-invalid row occurs, the exact matching producer's dependency
horizon is unknown, so affected materialized price-derived inputs remain NaN.
Events, labels, observed session dates, and unaffected feature cells are reused.
"""
import concurrent.futures, hashlib, json, os, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pipeline as p

BASE=p.OUT; R4=BASE/'r4'; DEST=R4/'full'; TARGET=json.loads((BASE/'R4_TARGETS.json').read_text())
CONTRACT=json.loads((BASE/'EXPERIMENT_CONTRACT_R4.json').read_text())
PANEL_HANDLE=None
COLS=['trade_date','ts_code','market_type','open','high','low','close','vol_ratio_60','amplitude_pct','high_20','zge_white_line','J']
SOURCE_FEATURES=['pct_chg','amplitude_pct','bar_close_pos','vol_ratio_60','amount_ratio_20','dd20','dist_white','dist_yellow','dist_bbi','J','macd_hist_scaled','user_v1_B1']
ANCHOR_FEATURES=['bars_since_anchor','dd_anchor_high','dist_anchor_low','volume_to_anchor']
EDIT=SOURCE_FEATURES+ANCHOR_FEATURES+p.PERSONAL
assert set(EDIT)==set(p.GLOBAL+p.PERSONAL)

def check_prices(g):
    for x in ['open','high','low','close']:g[x]=pd.to_numeric(g[x],errors='coerce')
    c,o,h,l=(g[x] for x in ['close','open','high','low'])
    return (np.isfinite(o)&np.isfinite(h)&np.isfinite(l)&np.isfinite(c)&(o>0)&(h>0)&(l>0)&(c>0)&
        (h+1e-7>=l)&(h+1e-7>=c)&(h+1e-7>=o)&(l<=c+1e-7)&(l<=o+1e-7))

def worker(task):
    global PANEL_HANDLE
    symbol,meta,ev,code_sha=task; dest=R4/'corrections';dest.mkdir(parents=True,exist_ok=True)
    out=dest/f'{symbol}.parquet'; stat=dest/f'{symbol}.json'
    if out.exists() and stat.exists():
        old=json.loads(stat.read_text())
        if old['output_sha256']==p.sha(out) and old['code_sha256']==code_sha and old['row_groups']==meta['row_groups']:return old
        raise ValueError('R4_CHECKPOINT_IDENTITY_DRIFT:'+symbol)
    if PANEL_HANDLE is None:PANEL_HANDLE=pq.ParquetFile(p.PANEL)
    g=PANEL_HANDLE.read_row_groups(meta['row_groups'],columns=COLS,use_threads=False).to_pandas()
    g=g.loc[g.ts_code.eq(symbol)].copy();g['trade_date']=p.dates8(g.trade_date);g=g.loc[g.trade_date.notna()&g.trade_date.le(p.ASOF)].sort_values('trade_date',kind='stable').reset_index(drop=True)
    if g.trade_date.duplicated().any():raise ValueError('R4_DUPLICATE_KEY:'+symbol)
    good=check_prices(g);bad=(~good).to_numpy();bad_count=int(bad.sum())
    if bad_count!=meta['invalid_all_history']:raise ValueError('R4_SOURCE_VALIDITY_COUNT_MISMATCH:'+symbol+':'+str(bad_count))
    tainted=np.maximum.accumulate(bad);days=g.trade_date.to_numpy(dtype='int64');where=pd.Index(days).get_indexer(ev.trade_date.astype('int64'))
    anchor=pd.Index(days).get_indexer(ev.anchor_date.astype('int64'))
    if (where<0).any() or (anchor<0).any() or (anchor>=where).any() or not good.iloc[where].all() or not good.iloc[anchor].all():raise ValueError('R4_EVENT_OR_ANCHOR_IDENTITY:'+symbol)
    path_bad=np.cumsum(bad,dtype='int64')[where]-np.cumsum(bad,dtype='int64')[anchor]>0
    tainted_event=tainted[where]
    c=pd.to_numeric(g.close,errors='coerce'); high20=pd.to_numeric(g.high_20,errors='coerce');white=pd.to_numeric(g.zge_white_line,errors='coerce')
    series=[pd.to_numeric(g.vol_ratio_60,errors='coerce'),pd.to_numeric(g.amplitude_pct,errors='coerce'),
        c/high20.where(high20>0)-1,c/white.where(white>0)-1,pd.to_numeric(g.J,errors='coerce')]
    calculated={name:p.rank_prior(s.where(good&~tainted)).iloc[where].to_numpy(dtype='float64') for name,s in zip(p.PERSONAL,series)}
    before=~tainted_event
    for name in p.PERSONAL:
        old=pd.to_numeric(ev[name],errors='coerce').to_numpy(dtype='float64')
        if not np.allclose(old[before],calculated[name][before],rtol=1e-12,atol=1e-12,equal_nan=True):raise ValueError('R4_UNAFFECTED_PARITY_FAILURE:'+symbol+':'+name)
        if not np.isnan(calculated[name][tainted_event]).all():raise ValueError('R4_TAINTED_PERSONAL_NOT_UNKNOWN:'+symbol)
    correction=ev[['ts_code','trade_date']+EDIT].copy().reset_index(drop=True)
    for name in p.PERSONAL:correction[name]=calculated[name]
    for name in SOURCE_FEATURES:correction.loc[tainted_event,name]=np.nan
    for name in ANCHOR_FEATURES:correction.loc[path_bad,name]=np.nan
    correction['source_prefix_tainted']=tainted_event;correction['invalid_anchor_path']=path_bad
    correction['first_invalid_date']=int(days[np.flatnonzero(bad)[0]])
    p.write_parquet_atomic(correction,out)
    summary={'symbol':symbol,'row_groups':meta['row_groups'],'source_rows':len(g),'invalid_all_history':bad_count,
        'first_invalid_date':int(days[np.flatnonzero(bad)[0]]),'events':len(ev),'tainted_events':int(tainted_event.sum()),
        'invalid_anchor_path_events':int(path_bad.sum()),'output_sha256':p.sha(out),'code_sha256':code_sha}
    p.atomic_json(stat,summary);return summary

def framehash(df):
    return hashlib.sha256(pd.util.hash_pandas_object(df,index=False).to_numpy().tobytes()).hexdigest()

def main():
    import sys
    code_sha=p.sha(Path(__file__));src=BASE/'r3/full/events_features_labels.parquet';source=pd.read_parquet(src)
    assert p.sha(src)==CONTRACT['input']['source_events_sha256']
    assert p.sha(BASE/'R4_TARGETS.json')==CONTRACT['input']['target_manifest_sha256']
    assert not source.duplicated(['ts_code','trade_date']).any()
    tasks=[]
    for symbol,meta in TARGET['target_symbols'].items():
        ev=source.loc[source.ts_code.eq(symbol),['ts_code','trade_date','anchor_date']+EDIT].copy()
        if len(ev):tasks.append((symbol,meta,ev,code_sha))
    R4.mkdir(exist_ok=True);DEST.mkdir(exist_ok=True);stats=[];t=time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=12) as pool:
        for item in pool.map(worker,tasks,chunksize=4):
            stats.append(item)
            if len(stats)%60==0 or len(stats)==len(tasks):print(json.dumps({'corrected_symbols':len(stats),'total':len(tasks),'elapsed_sec':round(time.time()-t,1)}),flush=True)
    corrections=pd.concat([pd.read_parquet(R4/'corrections'/f"{x['symbol']}.parquet") for x in stats],ignore_index=True)
    if corrections.duplicated(['ts_code','trade_date']).any():raise ValueError('R4_CORRECTION_DUPLICATE_KEY')
    original=source.set_index(['ts_code','trade_date'],drop=False);delta=corrections.set_index(['ts_code','trade_date'],drop=False)
    assert delta.index.isin(original.index).all()
    new=source.copy().set_index(['ts_code','trade_date'],drop=False)
    for col in EDIT:new.loc[delta.index,col]=delta[col]
    new=new.reset_index(drop=True)
    labelcols=['ts_code','trade_date','anchor_date','event_group','date_d1','date_d5','date_d10','y5','y10','R5','R10','label5_status','label10_status']
    pd.testing.assert_frame_equal(source[labelcols],new[labelcols],check_exact=True)
    p.write_parquet_atomic(new,DEST/'events_features_labels.parquet')
    session=BASE/'r3/full/observed_a_sessions.parquet';dest_session=DEST/'observed_a_sessions.parquet'
    if not dest_session.exists():os.link(session,dest_session)
    assert p.sha(session)==p.sha(dest_session)
    status=source[['ts_code','trade_date','anchor_key','anchor_wave']].copy()
    update=corrections[['ts_code','trade_date','source_prefix_tainted','invalid_anchor_path','first_invalid_date']]
    status=status.merge(update,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    status['source_prefix_tainted']=status.source_prefix_tainted.fillna(False).astype(bool)
    status['invalid_anchor_path']=status.invalid_anchor_path.fillna(False).astype(bool)
    status['source_event_basis']=np.where(status.source_prefix_tainted,'UNCERTAIN_AFTER_INVALID_PREFIX','NO_KNOWN_INVALID_PREFIX_UPSTREAM_FORMULA_UNCERTIFIED')
    p.write_parquet_atomic(status,DEST/'feature_validity_overlay.parquet')
    changes={col:int((source[col].notna()&new[col].isna()).sum()) for col in EDIT}
    # No values other than feature -> UNKNOWN may change.
    for col in EDIT:
        a=pd.to_numeric(source[col],errors='coerce').to_numpy(dtype=float);b=pd.to_numeric(new[col],errors='coerce').to_numpy(dtype=float)
        if np.any(~np.isnan(b)&~np.isclose(a,b,rtol=1e-12,atol=1e-12,equal_nan=True)):raise ValueError('R4_UNEXPECTED_NUMERIC_CHANGE:'+col)
    period=(status.trade_date//10000).astype(int);branches=np.select([status.anchor_key.fillna(False)&status.anchor_wave.fillna(False),status.anchor_key.fillna(False),status.anchor_wave.fillna(False)],['BOTH','KEY_ONLY','WAVE_ONLY'],default='INVALID')
    annual={str(year):{'events':int((period==year).sum()),'tainted':int(((period==year)&status.source_prefix_tainted).sum()),'invalid_anchor_path':int(((period==year)&status.invalid_anchor_path).sum())} for year in sorted(period.unique())}
    branch={b:{'events':int((branches==b).sum()),'tainted':int(((branches==b)&status.source_prefix_tainted).sum()),'invalid_anchor_path':int(((branches==b)&status.invalid_anchor_path).sum())} for b in ['KEY_ONLY','WAVE_ONLY','BOTH']}
    sessions=pd.read_parquet(dest_session).trade_date.to_numpy();folds=[]
    for cut,end in zip(CONTRACT['split']['training_cuts'],CONTRACT['split']['test_end']):
        tr,te,info=p.split_masks(new,sessions,cut,end);folds.append({**info,'train_events':int(tr.sum()),'test_events':int(te.sum()),'train_tainted':int((tr&status.source_prefix_tainted).sum()),'test_tainted':int((te&status.source_prefix_tainted).sum()),'train_invalid_anchor_path':int((tr&status.invalid_anchor_path).sum()),'test_invalid_anchor_path':int((te&status.invalid_anchor_path).sum())})
    result={'status':'FEATURE_MASK_COMPLETE_MODEL_NOT_YET_TRAINED','policy':'FROM_FIRST_INVALID_OHLC_DAY_ONWARD_MASK_POSSIBLY_DEPENDENT_SOURCE_INPUTS_AND_PERSONAL_RANKS;NO_ASSUMED_RECURSIVE_EXPIRY',
      'source_symbols_targeted':len(stats),'source_row_groups_read':sum(len(s['row_groups']) for s in stats),'source_rows_read':sum(s['source_rows'] for s in stats),
      'total_events':len(new),'tainted_events':int(status.source_prefix_tainted.sum()),'tainted_stocks':int(status.loc[status.source_prefix_tainted,'ts_code'].nunique()),
      'invalid_anchor_path_events':int(status.invalid_anchor_path.sum()),'newly_unknown_feature_cells':changes,
      'feature_na_count':{c:int(new[c].isna().sum()) for c in EDIT},'per_year':annual,'per_anchor_branch':branch,'per_fold':folds,
      'cohort_and_labels_unchanged':True,'label_fingerprint':framehash(source[labelcols]),'session_sha256':p.sha(dest_session),
      'R3_source_sha256':p.sha(src),'R4_events_sha256':p.sha(DEST/'events_features_labels.parquet'),
      'validity_overlay_sha256':p.sha(DEST/'feature_validity_overlay.parquet'),
      'upstream_formula_dependency':'CANNOT_CONFIRM_CURRENT_GENERATION_FORMULA_HASH_UNMATCHED','panel_rescan':'TARGETED_ROWGROUP_COLUMNS_ONLY',
      'feature_columns_used_for_fit':p.GLOBAL+p.PERSONAL,'event_flags_used_as_features':False,'event_and_label_recalculation':False}
    p.atomic_json(DEST/'FEATURE_MASK_REPORT.json',result);p.atomic_json(R4/'CORRECTIONS_COMPLETE.json',{'symbols':stats});print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
