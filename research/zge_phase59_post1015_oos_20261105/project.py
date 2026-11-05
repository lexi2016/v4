"""Causal stock-prefix canary and feature projection, never reads test outcome dates."""
import argparse, concurrent.futures, json, os, resource, time
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import common as c
from feature_logic import create_stock

os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
OUT=c.ROOT/'run'; OUT.mkdir(exist_ok=True)

def dump(name,x):
    (OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def project(end,codes=None):
    filt=(ds.field('trade_date')>=str(c.PREFIX))&(ds.field('trade_date')<=str(end))
    if codes is not None: filt=filt&ds.field('ts_code').isin(codes)
    table=ds.dataset(c.PANEL,format='parquet').to_table(columns=c.COLUMNS,filter=filt,use_threads=True)
    d=table.to_pandas(); del table
    code=d.ts_code.fillna('').astype(str); mt=d.market_type.fillna('').astype(str)
    a=code.str.fullmatch(r'\d{6}\.(SH|SZ)'); bj=code.str.fullmatch(r'\d{6}\.BJ')
    known=mt.isin(['A_SHARE','BJ']);bad=(mt.eq('A_SHARE')&~a)|(mt.eq('BJ')&~bj)|((a|bj)&known&~((a&mt.eq('A_SHARE'))|(bj&mt.eq('BJ'))))
    if bad.any():raise ValueError('MARKET_CODE_CONFLICT '+repr(d.loc[bad,['ts_code','market_type']].head().to_dict('records')))
    keep=(a&mt.eq('A_SHARE'))|(bj&mt.eq('BJ'))
    info={'physical_read':len(d),'valid_market_rows':int(keep.sum()),'market_unknown_rows':int(((a|bj)&~known).sum()),'excluded_basis_rows':int((keep&code.isin(c.EXCLUDED)).sum())}
    d=d.loc[keep&~code.isin(c.EXCLUDED)].copy(); d['trade_date']=d.trade_date.astype(int)
    if d.duplicated(['ts_code','trade_date']).any():raise ValueError('DUPLICATE_STOCK_DATE_STOP')
    return d,info

def profilemap():
    df=pd.read_parquet(c.PROFILE); assert not df.ts_code.duplicated().any()
    return df.set_index('ts_code').to_dict('index')

def complete_history_codes():
    """Footer-only proof that stock's source starts inside loaded prefix."""
    f=pq.ParquetFile(c.PANEL); names=f.schema_arrow.names;ci=names.index('ts_code');di=names.index('trade_date');bounds={};mixed=[]
    for j in range(f.metadata.num_row_groups):
        rg=f.metadata.row_group(j);cs=rg.column(ci).statistics;dt=rg.column(di).statistics
        if not cs or not dt or not cs.has_min_max or not dt.has_min_max:continue
        if cs.min==cs.max:bounds[cs.min]=min(str(dt.min),bounds.get(cs.min,'99999999'))
        else:mixed.append((str(cs.min),str(cs.max)))
    return {k for k,v in bounds.items() if v>=str(c.PREFIX) and not any(lo<=k<=hi for lo,hi in mixed)}

def task(arg):
    tc,g,profile,complete=arg
    return create_stock(g,profile,complete)

def canary():
    t=time.time();c.bindings(); codes=['600028.SH','000001.SZ','920006.BJ'];d,info=project(c.X_END,codes);pro=profilemap();complete=complete_history_codes();out=[]
    for tc in codes:
        g=d[d.ts_code.eq(tc)].copy();
        if len(g)<120:raise ValueError('CANARY_SOURCE_TOO_SHORT '+tc)
        full=create_stock(g,pro.get(tc),tc in complete)
        for date in [c.TRAIN,c.TEST[-1]]:
            trunc=create_stock(g[g.trade_date<=date],pro.get(tc),tc in complete)
            a=full[full.signal_date.eq(date)].reset_index(drop=True);b=trunc[trunc.signal_date.eq(date)].reset_index(drop=True)
            if len(a)!=1 or len(b)!=1:raise ValueError('CANARY_DATE_MISSING '+tc+' '+str(date))
            pd.testing.assert_frame_equal(a,b,check_dtype=False,check_exact=False,rtol=0,atol=1e-12)
            q=g.copy();later=q.trade_date>date
            for col in ('open','high','low','close','volume'):q.loc[later,col]=pd.to_numeric(q.loc[later,col],errors='coerce')*1.1
            pert=create_stock(q,pro.get(tc),tc in complete);p=pert[pert.signal_date.eq(date)].reset_index(drop=True)
            pd.testing.assert_frame_equal(a,p,check_dtype=False,check_exact=False,rtol=0,atol=1e-12)
            out.append({'stock':tc,'date':date,'prefix_and_future_perturbation':'PASS','source_prefix_rows':len(g[g.trade_date<=date]),'status':str(a.pool_status.iloc[0])})
    report={'status':'PASS','cases':out,'coverage':info,'wall_seconds':time.time()-t,'peak_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'formula_note':'Only OHLCV-derived full path recalculated; panel materialized lines use bound canonical producer and are not themselves future-disturbed'}
    dump('CANARY.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)

def full():
    if json.loads((OUT/'CANARY.json').read_text())['status']!='PASS':raise ValueError('CANARY_REQUIRED')
    t=time.time();c.bindings();d,info=project(c.X_END);d.to_parquet(OUT/'raw_prefix_20240101_20261028.parquet',index=False,compression='zstd')
    pro=profilemap();complete=complete_history_codes(); groups=list(d.groupby('ts_code',sort=True)); del d
    print(json.dumps({'stage':'PROJECT_LOADED','stocks':len(groups),**info},ensure_ascii=False),flush=True)
    results=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=12) as pool:
        pending=set();it=iter(groups)
        def submit():
            try:tc,g=next(it)
            except StopIteration:return False
            pending.add(pool.submit(task,(tc,g,pro.get(tc),tc in complete)));return True
        for _ in range(28):
            if not submit():break
        completed=0
        while pending:
            done,pending=concurrent.futures.wait(pending,return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                results.append(f.result());completed+=1
                submit()
            if completed and completed%500==0:print(json.dumps({'stage':'FEATURES','completed_stocks':completed,'elapsed':round(time.time()-t,1)}),flush=True)
    x=pd.concat(results,ignore_index=True);x.sort_values(['signal_date','ts_code'],inplace=True);x.to_parquet(OUT/'features_pre_oos.parquet',index=False,compression='zstd')
    coverage={}
    for date,g in x.groupby('signal_date'):
        coverage[str(date)]={'rows':len(g),'pool_status':g.pool_status.value_counts().to_dict(),'feature_observed':{z:int(g[z].notna().sum()) for z in c.FEATURES}}
    report={'status':'PASS','scope':'20261016..20261028 features only; no future outcome dates opened','input_counts':info,'stocks':len(groups),'feature_rows':len(x),'coverage':coverage,'features_sha256':c.sha(OUT/'features_pre_oos.parquet'),'raw_prefix_sha256':c.sha(OUT/'raw_prefix_20240101_20261028.parquet'),'wall_seconds':time.time()-t,'peak_rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'worker_count':12,'blas_threads_per_worker':1}
    dump('FEATURE_RECEIPT.json',report);print(json.dumps({'stage':'FEATURES_SAVED','rows':len(x),'stocks':len(groups),'status_by_date':{k:v['pool_status'] for k,v in coverage.items()},'wall_seconds':report['wall_seconds']},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['canary','full']);a=p.parse_args();canary() if a.stage=='canary' else full()
