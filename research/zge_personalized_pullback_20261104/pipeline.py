"""Point-in-time-design research proxy on a frozen, explicitly non-PIT panel.

All data access is read-only. Derived artifacts and checkpoints are written
only under the run output directory. No scheduler, API, gate, or order calls.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

OUT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/pullback_model_design_20261104/training_v1')
CONTRACT_PATH=OUT/'EXPERIMENT_CONTRACT_R2.json'
CONTRACT=json.loads(CONTRACT_PATH.read_text())
PANEL=CONTRACT['input']['selector_path']
COLS=['trade_date','ts_code','market_type','open','high','low','close','volume','pct_chg','amplitude_pct','bar_close_pos','vol_ratio_60','amount_ratio_20','high_20','BBI','zge_white_line','zge_yellow_line','J','macd_hist','user_v1_B1','user_v1_breakout','plry_volume_burst','c3_continuous_volume_price']
GLOBAL=CONTRACT['features']['global']; PERSONAL=CONTRACT['features']['personal_extra']
TIME0=20210101; ASOF=20261104

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1048576),b''):h.update(data)
    return h.hexdigest()

def atomic_json(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def dates8(x):
    if pd.api.types.is_datetime64_any_dtype(x): return pd.to_numeric(x.dt.strftime('%Y%m%d'),errors='coerce')
    s=x.astype('string').str.replace('-','',regex=False).str.slice(0,8)
    z=pd.to_numeric(s,errors='coerce')
    parsed=pd.to_datetime(s,format='%Y%m%d',errors='coerce')
    return z.where(parsed.notna())

def truth1(s):
    n=pd.to_numeric(s,errors='coerce')
    return n.eq(1).where(n.isin([0,1]),pd.NA).astype('boolean')

def rank_prior(s):
    # D is used only as the query; the denominator and references are D-250..D-1.
    s=pd.to_numeric(s,errors='coerce').replace([np.inf,-np.inf],np.nan)
    win=s.rolling(251,min_periods=61);rank=win.rank(method='average');count=win.count()
    return ((rank-1)/(count-1)).where((count>=61)&s.notna())

def process_stock(g):
    g=g.sort_values('trade_date',kind='stable').reset_index(drop=True).copy()
    if g.duplicated('trade_date').any():raise ValueError('DUPLICATE_STOCK_DATE:'+str(g['ts_code'].iloc[0]))
    for c in COLS[3:]:g[c]=pd.to_numeric(g[c],errors='coerce')
    c,o,h,l,v=(g[x] for x in ('close','open','high','low','volume'))
    valid=(np.isfinite(o)&np.isfinite(h)&np.isfinite(l)&np.isfinite(c)&(o>0)&(h>0)&(l>0)&(c>0)&(h+1e-7>=l)&(h+1e-7>=c)&(h+1e-7>=o)&(l<=c+1e-7)&(l<=o+1e-7))
    validv=np.isfinite(v)&(v>=0)
    key=truth1(g['user_v1_breakout']) & truth1(g['plry_volume_burst']) & (c>o).where(c.notna()&o.notna(),pd.NA).astype('boolean')
    wave=truth1(g['c3_continuous_volume_price']) & (c>o).where(c.notna()&o.notna(),pd.NA).astype('boolean') & (c>c.shift(1)).where(c.notna()&c.shift(1).notna(),pd.NA).astype('boolean')
    a=key|wave
    g['dd20']=c/g['high_20'].where(g['high_20']>0)-1
    g['dist_white']=c/g['zge_white_line'].where(g['zge_white_line']>0)-1
    g['dist_yellow']=c/g['zge_yellow_line'].where(g['zge_yellow_line']>0)-1
    g['dist_bbi']=c/g['BBI'].where(g['BBI']>0)-1
    g['macd_hist_scaled']=g['macd_hist']/c.where(c>0)
    for source,dest in zip(['vol_ratio_60','amplitude_pct','dd20','dist_white','J'],PERSONAL):g[dest]=rank_prior(g[source])
    anchor=None;events=[];groups={};unknown_anchor=0;unknown_pullback=0
    # Each symbol is processed independently; no filling across stocks.
    for i in range(len(g)):
        if not bool(valid.iloc[i]):
            if anchor is not None: unknown_pullback+=1
            continue
        if anchor is not None and (i-anchor['i']>15 or c.iloc[i]<0.98*anchor['low']):
            groups[anchor['date']].update(audit_group_end_date=int(g.trade_date.iloc[i]),audit_group_end_reason='EXPIRED' if i-anchor['i']>15 else 'BELOW_ANCHOR_LOW')
            anchor=None
        if anchor is None:
            av=a.iloc[i]
            if pd.isna(av):unknown_anchor+=1
            elif bool(av):
                if not bool(validv.iloc[i]) or v.iloc[i]<=0:unknown_anchor+=1
                else:
                    anchor={'i':i,'date':int(g.trade_date.iloc[i]),'low':float(l.iloc[i]),'high':float(h.iloc[i]),'volume':float(v.iloc[i]),'key':bool(key.iloc[i]) if not pd.isna(key.iloc[i]) else False,'wave':bool(wave.iloc[i]) if not pd.isna(wave.iloc[i]) else False}
                    groups[anchor['date']]={'audit_group_start_bar_index':i,'audit_group_expiry_bar_index':i+15,'audit_group_end_date':None,'audit_group_end_reason':'UNRESOLVED_AT_ASOF'}
            continue
        age=i-anchor['i']
        if age<2 or age>15 or int(g.trade_date.iloc[i])<TIME0 or int(g.trade_date.iloc[i])>ASOF:continue
        if not c.iloc[i] < .99*anchor['high']:continue
        shrink=None if not bool(validv.iloc[i]) else bool(v.iloc[i]<=.8*anchor['volume'])
        white=g['zge_white_line'].iloc[i];near=None if not np.isfinite(white) or white<=0 else bool(abs(c.iloc[i]/white-1)<=.03)
        if shrink is not True and near is not True:
            if shrink is None or near is None:unknown_pullback+=1
            continue
        row={'ts_code':str(g.ts_code.iloc[i]),'trade_date':int(g.trade_date.iloc[i]),'anchor_date':anchor['date'],
             'event_group':f"{g.ts_code.iloc[i]}:{anchor['date']}",'anchor_key':anchor['key'],'anchor_wave':anchor['wave'],
             'bars_since_anchor':age,'dd_anchor_high':float(c.iloc[i]/anchor['high']-1),'dist_anchor_low':float(c.iloc[i]/anchor['low']-1),
             'volume_to_anchor':float(v.iloc[i]/anchor['volume']) if bool(validv.iloc[i]) else np.nan}
        for col in GLOBAL+PERSONAL:
            if col not in row:row[col]=g[col].iloc[i]
        events.append(row)
    for row in events:row.update(groups[row['anchor_date']])
    px=g.loc[g.trade_date.ge(TIME0)&g.trade_date.le(ASOF),['ts_code','trade_date','open','close']].copy()
    px['price_valid']=valid.loc[px.index].to_numpy()
    stats={'symbol':str(g.ts_code.iloc[0]),'rows':len(g),'signal_period_rows':int(g.trade_date.ge(TIME0).sum()),'events':len(events),'unknown_anchor':unknown_anchor,'unknown_pullback':unknown_pullback,'invalid_price_rows':int((~valid).sum())}
    return events,px,stats

def write_parquet_atomic(df,path):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp');df.to_parquet(tmp,index=False,compression='zstd');os.replace(tmp,path)

def filter_a(df):
    df=df.copy();df['trade_date']=dates8(df['trade_date']);df['ts_code']=df['ts_code'].astype('string');df['market_type']=df['market_type'].astype('string')
    market=df['market_type'].isin(['A_SHARE','BJ'])
    matched=((df['market_type'].eq('A_SHARE')&df['ts_code'].str.fullmatch(r'\d{6}\.(SH|SZ)',na=False))|
             (df['market_type'].eq('BJ')&df['ts_code'].str.fullmatch(r'\d{6}\.BJ',na=False))).fillna(False)
    stats={'physical_rows':len(df),'non_a_rows':int((~market).sum()),'a_identity_conflicts':int((market&~matched).sum()),
      'bad_date_rows':int((matched&df.trade_date.isna()).sum())}
    df=df.loc[matched&df.trade_date.notna()&df.trade_date.le(ASOF)].copy();df['trade_date']=df.trade_date.astype('int64')
    return df,stats

def prepare_mixed(footer):
    d=OUT/'mixed_cache';d.mkdir(exist_ok=True);report=d/'MIXED_INPUT_REPORT.json'
    mixed=[g['id'] for g in footer['groups'] if not g['symbol'] or g['symbol'][0]!=g['symbol'][1]]
    if report.exists():
        r=json.loads(report.read_text())
        if r['row_groups']!=mixed or any(not (d/x['file']).exists() or sha(d/x['file'])!=x['sha256'] for x in r['symbols'].values()):raise ValueError('MIXED_CACHE_MISMATCH')
        return r
    pf=pq.ParquetFile(PANEL);pieces={}; counts={'physical_rows':0,'non_a_rows':0,'a_identity_conflicts':0,'bad_date_rows':0}
    for rid in mixed:
        df,st=filter_a(pf.read_row_group(rid,columns=COLS,use_threads=False).to_pandas())
        for k in counts:counts[k]+=st[k]
        for sym,g in df.groupby('ts_code',observed=True,sort=False):pieces.setdefault(str(sym),[]).append(g)
    symbols={}
    for symbol,groups in pieces.items():
        f=d/f'{symbol}.parquet';joined=pd.concat(groups,ignore_index=True);write_parquet_atomic(joined,f)
        symbols[symbol]={'file':f.name,'rows':len(joined),'sha256':sha(f)}
    result={'row_groups':mixed,'counts':counts,'symbols':symbols,'source_panel_sha256_producer_declared':CONTRACT['input']['selector_declared_sha256']}
    atomic_json(report,result);return result

def scan_part(arg):
    part,groups,mixed_symbols,run_dir=arg; run_dir=Path(run_dir); pp=run_dir/'parts'; pp.mkdir(parents=True,exist_ok=True)
    eventp=pp/f'events_{part:05d}.parquet';pricep=pp/f'prices_{part:05d}.parquet';statp=pp/f'stats_{part:05d}.json'
    if statp.exists() and eventp.exists() and pricep.exists():
        old=json.loads(statp.read_text())
        if old['source_groups']==groups and old['mixed_symbols']==mixed_symbols and old['event_sha256']==sha(eventp) and old['price_sha256']==sha(pricep):return old
        raise ValueError('CHECKPOINT_IDENTITY_MISMATCH:'+str(statp))
    pf=pq.ParquetFile(PANEL)
    if groups:df,rawstats=filter_a(pf.read_row_groups(groups,columns=COLS,use_threads=False).to_pandas())
    else:df=pd.DataFrame(columns=COLS);rawstats={'physical_rows':0,'non_a_rows':0,'a_identity_conflicts':0,'bad_date_rows':0}
    caches=[pd.read_parquet(OUT/'mixed_cache'/f'{symbol}.parquet') for symbol in mixed_symbols]
    if caches:df=pd.concat([df,*caches],ignore_index=True)
    if run_dir.name=='canary':write_parquet_atomic(df,run_dir/f'canary_input_{part:05d}.parquet')
    syms=[];events=[];prices=[]
    for _,g in df.groupby('ts_code',sort=False,observed=True):
        ev,px,st=process_stock(g);events.extend(ev);prices.append(px);syms.append(st)
    audit=['audit_group_start_bar_index','audit_group_expiry_bar_index','audit_group_end_date','audit_group_end_reason']
    evdf=pd.DataFrame(events,columns=['ts_code','trade_date','anchor_date','event_group','anchor_key','anchor_wave']+audit+GLOBAL+PERSONAL)
    pxdf=pd.concat(prices,ignore_index=True) if prices else pd.DataFrame({'ts_code':pd.Series(dtype='string'),'trade_date':pd.Series(dtype='int64'),'open':pd.Series(dtype='float64'),'close':pd.Series(dtype='float64'),'price_valid':pd.Series(dtype='bool')})
    # Explicit empty schema avoids null-typed per-part columns.
    for col in ['ts_code','event_group','audit_group_end_reason']:evdf[col]=evdf[col].astype('string')
    for col in ['anchor_key','anchor_wave']:evdf[col]=evdf[col].astype('boolean')
    for col in ['trade_date','anchor_date','audit_group_start_bar_index','audit_group_expiry_bar_index','audit_group_end_date']:evdf[col]=pd.to_numeric(evdf[col],errors='coerce').astype('Int64')
    for col in GLOBAL+PERSONAL:evdf[col]=pd.to_numeric(evdf[col],errors='coerce').astype('float64').replace([np.inf,-np.inf],np.nan)
    write_parquet_atomic(evdf,eventp);write_parquet_atomic(pxdf,pricep)
    result={'part':part,'source_groups':groups,'mixed_symbols':mixed_symbols,'physical_rows':rawstats['physical_rows'],'a_identity_rows':len(df),'non_a_rows':rawstats['non_a_rows'],'a_identity_conflicts':rawstats['a_identity_conflicts'],'bad_date_rows':rawstats['bad_date_rows'],'symbols':syms,'event_rows':len(evdf),'price_rows':len(pxdf),'event_sha256':sha(eventp),'price_sha256':sha(pricep)}
    atomic_json(statp,result);return result

def group_batches(footer,mixed_report,canary):
    # A single symbol may span several row groups. Bind all its groups together.
    by_symbol={}
    for g in footer['groups']:
        bounds=g['symbol']
        if bounds and bounds[0]==bounds[1]:by_symbol.setdefault(bounds[0],[]).append(g['id'])
    wanted=['600519.SH','002865.SZ','920510.BJ']
    missing=[s for s in wanted if s not in by_symbol]
    if missing:raise ValueError('CANARY_SYMBOL_NOT_IN_SINGLE_SYMBOL_FOOTER:'+','.join(missing))
    mixed_symbols=set(mixed_report['symbols']); chosen=next((s for s in sorted(mixed_symbols) if s not in wanted),None)
    if chosen:wanted.append(chosen)
    groups=[(by_symbol.get(s,[]),[s] if s in mixed_symbols else []) for s in wanted]
    if canary:return groups
    chunk=[];cache=[]
    for symbol in sorted((set(by_symbol)|mixed_symbols)-set(wanted)):
        ids=by_symbol.get(symbol,[])
        if chunk and len(chunk)+len(ids)>24:groups.append((chunk,cache));chunk=[];cache=[]
        chunk.extend(ids)
        if symbol in mixed_symbols:cache.append(symbol)
    if chunk or cache:groups.append((chunk,cache))
    return groups

def assign_labels(ev,px,sessions):
    session_index=pd.Index(sessions);pos=session_index.get_indexer(ev.trade_date.astype('int64'))
    if (pos<0).any():raise ValueError('EVENT_DATE_ABSENT_FROM_OBSERVED_SESSIONS')
    for n in [1,5,10]:
        idx=pos+n; ev[f'date_d{n}']=pd.Series(np.where(idx<len(sessions),sessions[np.minimum(idx,len(sessions)-1)],-1),dtype='int64')
    entry=px[['ts_code','trade_date','open','price_valid']].rename(columns={'trade_date':'date_d1','open':'open_d1','price_valid':'entry_price_valid'})
    ev=ev.merge(entry,on=['ts_code','date_d1'],how='left',validate='many_to_one')
    for n in [5,10]:
        target=px[['ts_code','trade_date','close','price_valid']].rename(columns={'trade_date':f'date_d{n}','close':f'close_d{n}','price_valid':f'target{n}_price_valid'})
        ev=ev.merge(target,on=['ts_code',f'date_d{n}'],how='left',validate='many_to_one')
        known=(ev.date_d1.gt(0)&ev[f'date_d{n}'].gt(0)&ev.entry_price_valid.fillna(False)&ev[f'target{n}_price_valid'].fillna(False)&ev.open_d1.gt(0)&ev[f'close_d{n}'].gt(0))
        ev[f'R{n}']=(ev[f'close_d{n}']/ev.open_d1-1).where(known)
        ev[f'y{n}']=pd.Series(np.where(known,np.where(ev[f'R{n}']>0,1,0),-1),dtype='int8')
        ev[f'label{n}_status']=np.where(known,'KNOWN','UNKNOWN_MISSING_OR_INVALID_OR_UNMATURED')
    return ev

def combine_and_label(run_dir,stats):
    run_dir=Path(run_dir);parts=run_dir/'parts'; allsymbols=[s['symbol'] for st in stats for s in st['symbols']]
    if len(allsymbols)!=len(set(allsymbols)):raise ValueError('CROSS_PART_STOCK_SPLIT_OR_DUPLICATION')
    ev=pd.concat([pd.read_parquet(parts/f"events_{s['part']:05d}.parquet") for s in stats],ignore_index=True)
    px=pd.concat([pd.read_parquet(parts/f"prices_{s['part']:05d}.parquet") for s in stats],ignore_index=True)
    if px.duplicated(['ts_code','trade_date']).any():raise ValueError('DUPLICATE_PRICE_KEYS')
    if ev.duplicated(['ts_code','trade_date']).any():raise ValueError('DUPLICATE_EVENT_KEYS')
    sessions=np.sort(px.trade_date.unique().astype('int64'));write_parquet_atomic(pd.DataFrame({'trade_date':sessions}),run_dir/'observed_a_sessions.parquet')
    ev=assign_labels(ev,px,sessions)
    write_parquet_atomic(ev,run_dir/'events_features_labels.parquet')
    mixed=json.loads((OUT/'mixed_cache'/'MIXED_INPUT_REPORT.json').read_text())['counts']
    summary={'physical_rows':sum(s['physical_rows'] for s in stats)+mixed['physical_rows'],'a_identity_rows':sum(s['a_identity_rows'] for s in stats),
      'non_a_rows':sum(s['non_a_rows'] for s in stats)+mixed['non_a_rows'],'a_identity_conflicts':sum(s['a_identity_conflicts'] for s in stats)+mixed['a_identity_conflicts'],'bad_date_rows':sum(s['bad_date_rows'] for s in stats)+mixed['bad_date_rows'],
      'symbols':len(allsymbols),'sessions':len(sessions),'events':len(ev),'y10_known':int(ev.y10.ge(0).sum()),'y10_unknown':int(ev.y10.lt(0).sum()),'y5_known':int(ev.y5.ge(0).sum()),
      'unknown_anchor':sum(q['unknown_anchor'] for s in stats for q in s['symbols']),'unknown_pullback':sum(q['unknown_pullback'] for s in stats for q in s['symbols']),
      'invalid_price_rows':sum(q['invalid_price_rows'] for s in stats for q in s['symbols']),
      'calendar_status':'OBSERVED_PANEL_SESSION_CALENDAR_UNCERTIFIED','event_sha256':sha(run_dir/'events_features_labels.parquet'),'session_sha256':sha(run_dir/'observed_a_sessions.parquet')}
    atomic_json(run_dir/'DATA_SUMMARY.json',summary);return summary

def scan(args):
    footer=json.loads(Path(args.footer).read_text());run_dir=OUT/('canary' if args.canary else 'full');run_dir.mkdir(parents=True,exist_ok=True)
    mixed=prepare_mixed(footer);batches=group_batches(footer,mixed,args.canary);tasks=[(i,g,m,str(run_dir)) for i,(g,m) in enumerate(batches)]
    if not args.canary:
        # Reuse matching immutable canary parts instead of re-reading the same stocks.
        canary_parts=OUT/'canary'/'parts';target=run_dir/'parts';target.mkdir(exist_ok=True)
        for i,g,m,_ in tasks[:4]:
            s=canary_parts/f'stats_{i:05d}.json'
            if not s.exists():continue
            old=json.loads(s.read_text())
            if old['source_groups']==g and old['mixed_symbols']==m:
                for stem,ext in [('stats','json'),('events','parquet'),('prices','parquet')]:
                    src=canary_parts/f'{stem}_{i:05d}.{ext}';dst=target/src.name
                    if not dst.exists():os.link(src,dst)
    if args.canary:
        stats=[scan_part(x) for x in tasks]
    else:
        stats=[];begin=time.time()
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
            for result in pool.map(scan_part,tasks,chunksize=1):
                stats.append(result)
                if len(stats)%10==0 or len(stats)==len(tasks):
                    print(json.dumps({'completed_parts':len(stats),'total_parts':len(tasks),'physical_rows_completed':sum(s['physical_rows'] for s in stats),'elapsed_sec':round(time.time()-begin,1)}),flush=True)
                    atomic_json(run_dir/'PROGRESS.json',{'completed_parts':len(stats),'total_parts':len(tasks),'elapsed_sec':round(time.time()-begin,1)})
    atomic_json(run_dir/'PARTS_COMPLETE.json',{'parts':stats})
    print(json.dumps(combine_and_label(run_dir,stats),ensure_ascii=False),flush=True)

def split_masks(ev,sessions,cut,end):
    cutn=int(cut.replace('-',''));endn=int(end.replace('-',''));idx=np.searchsorted(sessions,cutn,side='right')
    start=idx+10
    if start>=len(sessions):raise ValueError('NO_TEST_AFTER_EMBARGO')
    first=int(sessions[start]);valid=ev.y10.ge(0)
    train=valid & ev.trade_date.le(cutn) & ev.date_d10.le(cutn)
    test=valid & ev.trade_date.ge(first)&ev.trade_date.le(endn)
    testgroups=set(ev.loc[test,'event_group']);before=int(train.sum());train &= ~ev.event_group.isin(testgroups)
    if len(set(ev.loc[train,'event_group'])&testgroups):raise AssertionError('SPLIT_EVENT_GROUP_LEAK')
    if not ev.loc[train,'date_d10'].le(cutn).all():raise AssertionError('TRAIN_LABEL_AFTER_CUT')
    if int(np.searchsorted(sessions,first))-idx<10:raise AssertionError('EMBARGO_FAILURE')
    return train,test,{'cut':cutn,'first_test_session':first,'test_end':endn,'embargo_sessions':int(np.searchsorted(sessions,first)-idx),'group_purge_rows':before-int(train.sum())}

def model_predict_subprocess(model,features,out):
    script=Path(__file__).resolve()
    p=subprocess.run([sys.executable,str(script),'predict','--model',str(model),'--features',str(features),'--output',str(out)],capture_output=True,text=True)
    if p.returncode:raise RuntimeError('LOAD_PREDICT_FAILED:'+p.stderr[-3000:])

def fit(args):
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.dummy import DummyClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score,log_loss,brier_score_loss,accuracy_score,average_precision_score
    from threadpoolctl import threadpool_limits
    run_dir=OUT/('canary' if args.canary else 'full');ev=pd.read_parquet(run_dir/'events_features_labels.parquet');sessions=pd.read_parquet(run_dir/'observed_a_sessions.parquet').trade_date.to_numpy()
    if not len(ev):raise ValueError('NO_EVENTS')
    if args.canary:canary_checks(ev,sessions)
    folds=list(zip(CONTRACT['split']['training_cuts'],CONTRACT['split']['test_end']))
    if args.canary:folds=folds[-1:]
    results=[]; predictions=[]
    for fold,(cut,end) in enumerate(folds,1):
        tr,te,split=split_masks(ev,sessions,cut,end);train=ev.loc[tr];test=ev.loc[te]
        if len(train)<30 or len(test)<10 or train.y10.nunique()<2 or test.y10.nunique()<2:raise ValueError('FOLD_INSUFFICIENT:'+str((split,len(train),len(test))))
        y=train.y10.astype(int);actual=test.y10.astype(int)
        base=HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=15,learning_rate=.06,min_samples_leaf=30,l2_regularization=1.0,early_stopping=False,random_state=42)
        models={'global':(base,GLOBAL),'personal':(HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=15,learning_rate=.06,min_samples_leaf=30,l2_regularization=1.0,early_stopping=False,random_state=42),GLOBAL+PERSONAL),
            'logistic':(make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),LogisticRegression(max_iter=400,random_state=42)),GLOBAL),
            'majority':(DummyClassifier(strategy='prior'),GLOBAL)}
        row={'fold':fold,**split,'train_count':len(train),'test_count':len(test),'train_positive_rate':float(y.mean()),'test_positive_rate':float(actual.mean()),'models':{}}
        pred=test[['ts_code','trade_date','anchor_date','event_group','date_d10','y10','R10']].copy()
        for name,(est,cols) in models.items():
            with threadpool_limits(limits=args.threads):est.fit(train[cols].astype(float),y);score=est.predict_proba(test[cols].astype(float))[:,1]
            pred[name+'_score']=score
            row['models'][name]={'ROC_AUC':float(roc_auc_score(actual,score)),'log_loss':float(log_loss(actual,score,labels=[0,1])),
                'Brier_uncalibrated_score':float(brier_score_loss(actual,score)),'accuracy_at_0.5':float(accuracy_score(actual,score>=.5)),'average_precision':float(average_precision_score(actual,score))}
            mp=run_dir/f'fold{fold}_{name}.joblib';joblib.dump({'estimator':est,'feature_columns':cols,'contract_sha256':sha(CONTRACT_PATH),'score_is_calibrated':False},mp,compress=3)
            sample=test[cols].head(20).copy();sample_path=run_dir/f'fold{fold}_{name}_parity_input.parquet';write_parquet_atomic(sample,sample_path)
            output=run_dir/f'fold{fold}_{name}_parity_output.npy';model_predict_subprocess(mp,sample_path,output)
            loaded=np.load(output);expected=est.predict_proba(sample.astype(float))[:,1]
            if not np.allclose(loaded,expected,rtol=1e-12,atol=1e-12):raise AssertionError('MODEL_FRESH_PROCESS_PARITY_FAILED:'+name)
            row['models'][name]['model_path']=str(mp);row['models'][name]['model_sha256']=sha(mp);row['models'][name]['fresh_process_parity']='PASS'
        row['paired_auc_difference']=row['models']['personal']['ROC_AUC']-row['models']['global']['ROC_AUC']
        row['paired_log_loss_difference']=row['models']['personal']['log_loss']-row['models']['global']['log_loss']
        results.append(row);pred['fold']=fold;predictions.append(pred)
        atomic_json(run_dir/'FIT_CHECKPOINT.json',{'completed_folds':results,'status':'IN_PROGRESS'});print(json.dumps(row),flush=True)
    allp=pd.concat(predictions,ignore_index=True);write_parquet_atomic(allp,run_dir/'predictions.parquet')
    summary={'folds':results,'predictions_sha256':sha(run_dir/'predictions.parquet'),'score_semantics':'UNCALIBRATED_MODEL_SCORES','decision':'DIRECTION_ONLY','sealed':'NOT_SEALED_ALL_EXPOSED','is_strategy_or_tradability_validation':False}
    atomic_json(run_dir/'METRICS.json',summary);atomic_json(run_dir/'FIT_CHECKPOINT.json',{'completed_folds':results,'status':'COMPLETE'})

def canary_checks(ev,sessions):
    # Checks actual anchor ordering and session label mapping; missing next session never slides.
    if not ev.anchor_date.lt(ev.trade_date).all():raise AssertionError('NONPAST_ANCHOR')
    pos=pd.Index(sessions).get_indexer(ev.trade_date.astype(int)); valid=pos+10<len(sessions)
    if not np.array_equal(ev.loc[valid,'date_d10'].astype(int),sessions[pos[valid]+10]):raise AssertionError('SESSION_ALIGNMENT')
    if not ev.loc[ev.open_d1.isna(),'y10'].eq(-1).all():raise AssertionError('MISSING_D1_FILLED')
    if ev[['ts_code','trade_date']].duplicated().any():raise AssertionError('DUPLICATE_EVENT')
    for cut,end in zip(CONTRACT['split']['training_cuts'],CONTRACT['split']['test_end']):split_masks(ev,sessions,cut,end)

def main():
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True)
    q=sp.add_parser('scan');q.add_argument('--footer',required=True);q.add_argument('--workers',type=int,default=12);q.add_argument('--canary',action='store_true');q.set_defaults(fn=scan)
    q=sp.add_parser('fit');q.add_argument('--threads',type=int,default=12);q.add_argument('--canary',action='store_true');q.set_defaults(fn=fit)
    q=sp.add_parser('predict');q.add_argument('--model',required=True);q.add_argument('--features',required=True);q.add_argument('--output',required=True)
    q.set_defaults(fn=lambda a:np.save(a.output,__import__('joblib').load(a.model)['estimator'].predict_proba(pd.read_parquet(a.features).astype(float))[:,1]))
    args=p.parse_args();args.fn(args)
if __name__=='__main__':main()
