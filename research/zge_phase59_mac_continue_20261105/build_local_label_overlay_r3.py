"""Versioned local-source labels for existing P59 tail keys; no feature rebuild."""
import concurrent.futures,hashlib,json,os,resource,threading,time
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import runtime as r
from local_label_canary import ROOT,R4,CONTRACT,PANEL,SESSION,PARTS,CLOUD,stats_map

TLS=threading.local();IDENT='LOCAL_PANEL_QFQ_ASOF_20261104_OPEN_TO_OPEN_T5_V1';ASOF=20261104;NWORK=8

def task(st,codes,dates):
    part=int(st['part']);p=PARTS/f'prices_{part:05d}.parquet';sha=r.sha(p)
    if sha!=st['price_sha256']:raise ValueError('PRICE_CACHE_HASH_DRIFT:'+str(part))
    cache=pd.read_parquet(p,columns=['ts_code','trade_date','open','price_valid'])
    cache=cache[cache.ts_code.isin(codes)&cache.trade_date.isin(dates)].copy()
    if not hasattr(TLS,'pf'):TLS.pf=pq.ParquetFile(PANEL)
    raw=TLS.pf.read_row_groups(st['source_groups'],columns=['ts_code','trade_date','market_type','open','volume'],use_threads=False).to_pandas()
    total=len(raw);raw.trade_date=pd.to_numeric(raw.trade_date,errors='coerce');raw=raw[raw.ts_code.isin(codes)&raw.trade_date.isin(dates)].copy()
    market=((raw.market_type.eq('A_SHARE')&raw.ts_code.str.fullmatch(r'\d{6}\.(SH|SZ)'))|(raw.market_type.eq('BJ')&raw.ts_code.str.fullmatch(r'\d{6}\.BJ')))
    if not market.all():raise ValueError('PANEL_MARKET_CONFLICT:'+str(part))
    if cache.duplicated(['ts_code','trade_date']).any() or raw.duplicated(['ts_code','trade_date']).any():raise ValueError('PART_DUPLICATE_KEYS:'+str(part))
    raw=raw.rename(columns={'open':'panel_open'});j=cache.merge(raw,on=['ts_code','trade_date'],how='outer',validate='one_to_one',indicator=True)
    if not j['_merge'].eq('both').all():raise ValueError('CACHE_PANEL_MISSING_KEY:'+str(part))
    if not np.isclose(j.open,j.panel_open,rtol=1e-9,atol=1e-9,equal_nan=True).all():raise ValueError('CACHE_PANEL_OPEN_MISMATCH:'+str(part))
    return j.drop(columns=['_merge','panel_open','market_type']),{'part':part,'price_cache_sha256':sha,'source_groups':st['source_groups'],'physical_rows_read':total,'selected_key_rows':len(j)}

def main():
    start=time.time();co=json.loads(CONTRACT.read_text());excluded=set(co['input']['excluded_retained_history_codes'])
    mixed=json.loads((R4/'mixed_cache/MIXED_INPUT_REPORT.json').read_text())
    if set(mixed['symbols'])!=excluded:raise ValueError('MIXED_NONEXCLUDED_NEEDS_SEPARATE_BINDING_STOP')
    src=pd.read_parquet(CLOUD,columns=['ts_code','signal_date','status_t5','ret_t5_pct','entry_date','entry_open_px','exit_date_t5'])
    if len(src)!=303161 or src.duplicated(['ts_code','signal_date']).any():raise ValueError('CLOUD_KEY_CONFLICT')
    tail=src[(src.signal_date>20261008)&src.signal_date.le(20261015)&src.status_t5.eq('PENDING')].copy().reset_index(drop=True)
    if len(tail)!=6664:raise ValueError('TAIL_COHORT_CHANGED')
    parent=pd.read_parquet(ROOT/'full_hard_replay_v1/fit_rows_and_masks.parquet',columns=['ts_code','signal_date'])
    overlap=tail[['ts_code','signal_date']].merge(parent,on=['ts_code','signal_date'],how='inner')
    if len(overlap):raise ValueError('TAIL_ALREADY_FIT_PARENT')
    session=pd.read_parquet(SESSION).trade_date.to_numpy(dtype='int64')
    if len(session)!=len(set(session)) or not (np.diff(session)>0).all() or session[-1]!=ASOF:raise ValueError('SESSION_BINDING_INVALID')
    idx=np.searchsorted(session,tail.signal_date);within=(idx<len(session))&(session[np.minimum(idx,len(session)-1)]==tail.signal_date)&(idx+6<len(session))
    tail['local_entry_date']=np.where(within,session[np.minimum(idx+1,len(session)-1)],-1)
    tail['local_exit_date']=np.where(within,session[np.minimum(idx+6,len(session)-1)],-1)
    dates=set(tail.loc[within,'local_entry_date'])|set(tail.loc[within,'local_exit_date'])
    allcodes=set(tail.ts_code)-excluded;by,_=stats_map();known=allcodes&set(by);missing=allcodes-known
    parts={int(by[tc]['part']):by[tc] for tc in known};groups=[g for s in parts.values() for g in s['source_groups']]
    if len(groups)!=len(set(groups)):raise ValueError('SOURCE_GROUP_REUSED_ACROSS_PARTS')
    tasks=[]
    for st in parts.values():
        tcset={x['symbol'] for x in st['symbols']}&known
        if set(st['mixed_symbols'])&tcset:raise ValueError('UNEXPECTED_MIXED_INCLUDED')
        if tcset:tasks.append((st,tcset,dates))
    checkpoint=ROOT/'inputs/LOCAL_PROJECTED_PRICE_CHECKPOINT.parquet';checkpoint_meta=ROOT/'inputs/LOCAL_PROJECTED_PRICE_CHECKPOINT.json'
    request={'source_generation':co['input']['generation'],'codes':sorted(known),'dates':sorted(int(d) for d in dates),'groups':sorted(groups)}
    request_sha=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    if checkpoint.exists() and checkpoint_meta.exists():
        cm=json.loads(checkpoint_meta.read_text())
        if cm['request_sha256']!=request_sha or cm['price_sha256']!=r.sha(checkpoint):raise ValueError('PROJECTED_PRICE_CHECKPOINT_MISMATCH')
        prices=pd.read_parquet(checkpoint);aud=cm['cache_parts'];print(json.dumps({'checkpoint':'REUSED','rows':len(prices)}),flush=True)
    else:
        if checkpoint.exists() or checkpoint_meta.exists():raise ValueError('INCOMPLETE_PROJECTED_PRICE_CHECKPOINT')
        results=[];aud=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=NWORK) as pool:
            fs=[pool.submit(task,*a) for a in tasks]
            for i,f in enumerate(concurrent.futures.as_completed(fs),1):
                v,aa=f.result();results.append(v);aud.append(aa)
                if i%30==0 or i==len(fs):print(json.dumps({'completed_parts':i,'total_parts':len(fs),'elapsed_s':round(time.time()-start,2),'peak_rss_bytes':int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}),flush=True)
        prices=pd.concat(results,ignore_index=True)
        if prices.duplicated(['ts_code','trade_date']).any():raise ValueError('CROSS_PART_PRICE_KEY_CONFLICT')
        prices.to_parquet(checkpoint,index=False,compression='zstd');cm={'request_sha256':request_sha,'price_sha256':r.sha(checkpoint),'cache_parts':aud}
        checkpoint_meta.write_text(json.dumps(cm,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'checkpoint':'SAVED','sha256':cm['price_sha256'],'rows':len(prices)}),flush=True)
    if prices.duplicated(['ts_code','trade_date']).any():raise ValueError('CROSS_PART_PRICE_KEY_CONFLICT')
    ent=prices.rename(columns={'trade_date':'local_entry_date','open':'local_entry_open','volume':'local_entry_volume','price_valid':'local_entry_valid'})
    ext=prices.rename(columns={'trade_date':'local_exit_date','open':'local_exit_open','volume':'local_exit_volume','price_valid':'local_exit_valid'})
    tail=tail.merge(ent,on=['ts_code','local_entry_date'],how='left',validate='many_to_one').merge(ext,on=['ts_code','local_exit_date'],how='left',validate='many_to_one')
    # Convert every boolean to a NumPy bool array BEFORE inversion or selection.
    def known_bool(x):return pd.Series(x).fillna(False).to_numpy(dtype=np.bool_)
    regression=known_bool(pd.Series([True,False,None],dtype=object))
    if regression.tolist()!=[True,False,False] or (~regression).tolist()!=[False,True,True]:raise ValueError('BOOLEAN_NA_REGRESSION')
    E=pd.to_numeric(tail.local_entry_open,errors='coerce').to_numpy(dtype=float,na_value=np.nan)
    X=pd.to_numeric(tail.local_exit_open,errors='coerce').to_numpy(dtype=float,na_value=np.nan)
    EV=pd.to_numeric(tail.local_entry_volume,errors='coerce').to_numpy(dtype=float,na_value=np.nan)
    XV=pd.to_numeric(tail.local_exit_volume,errors='coerce').to_numpy(dtype=float,na_value=np.nan)
    conditions=[known_bool(tail.ts_code.isin(excluded)),~known_bool(within),known_bool(tail.local_exit_date.gt(ASOF)),
       known_bool(tail.local_exit_date.le(20261015)),known_bool(tail.ts_code.isin(missing)),
       np.isnan(E),np.isnan(X),~known_bool(tail.local_entry_valid),~known_bool(tail.local_exit_valid),
       ~np.isfinite(E)|(E<=0),~np.isfinite(X)|(X<=0),~np.isfinite(EV)|(EV<=0),~np.isfinite(XV)|(XV<=0)]
    if any(x.dtype!=np.bool_ for x in conditions):raise ValueError('NON_BOOLEAN_SELECTION_CONDITION')
    reason=np.select(conditions,
       ['EXCLUDED_RETAINED_ORIGINAL_BASIS','UNKNOWN_SESSION_MAP','UNKNOWN_UNMATURED','NOT_AFTER_PARENT_LABEL_END','UNKNOWN_STOCK_CACHE_ABSENT',
        'UNKNOWN_ENTRY_PRICE_MISSING','UNKNOWN_EXIT_PRICE_MISSING','UNKNOWN_ENTRY_OHLC_INVALID','UNKNOWN_EXIT_OHLC_INVALID',
        'UNKNOWN_ENTRY_OPEN_NONPOSITIVE','UNKNOWN_EXIT_OPEN_NONPOSITIVE','UNKNOWN_ENTRY_VOLUME','UNKNOWN_EXIT_VOLUME'],default='KNOWN_LOCAL_LABEL')
    known_mask=reason=='KNOWN_LOCAL_LABEL';ret=np.full(len(tail),np.nan,dtype=float)
    ret[known_mask]=(X[known_mask]/E[known_mask]-1)*100
    if np.isfinite(ret[~known_mask]).any():raise ValueError('UNKNOWN_LABEL_NOT_NAN')
    tail['local_label_status']=reason;tail['local_ret_t5_pct']=ret
    # Regression for the exact local canary and the bool-inversion failure.
    canary=json.loads((ROOT/'LOCAL_V1_CANARY.json').read_text())
    for sample in canary['samples']:
        row=tail[(tail.ts_code==sample['ts_code'])&(tail.signal_date==sample['signal_date'])]
        if len(row)!=1 or row.local_label_status.iloc[0]!='KNOWN_LOCAL_LABEL':raise ValueError('CANARY_LOCAL_STATUS_REGRESSION:'+sample['ts_code'])
        for k in ['local_entry_date','local_exit_date','local_entry_open','local_exit_open','local_ret_t5_pct']:
            expected=sample[{'local_entry_date':'entry_date','local_exit_date':'exit_date'}.get(k,k)]
            if not np.isclose(float(row[k].iloc[0]),float(expected),rtol=0,atol=1e-12):raise ValueError('CANARY_LOCAL_VALUE_REGRESSION:'+sample['ts_code']+':'+k)
    if not (reason=='KNOWN_LOCAL_LABEL').any():raise ValueError('NO_KNOWN_LOCAL_LABELS')
    tail=tail.rename(columns={'status_t5':'cloud_original_status_t5','ret_t5_pct':'cloud_original_ret_t5_pct','entry_date':'cloud_original_entry_date',
        'entry_open_px':'cloud_original_entry_open_px','exit_date_t5':'cloud_original_exit_date_t5'})
    tail['local_label_identity']=IDENT;tail['local_generation']=co['input']['generation'];tail['local_selector_sha256_producer_declared']=co['input']['selector_declared_sha256']
    tail['calendar_semantics']='OBSERVED_PANEL_SESSION_PROXY_UNCERTIFIED';tail['cross_source_equivalence']='CANNOT_CONFIRM';tail['parent_fit_key_overlap']=False
    target=ROOT/'inputs/LOCAL_LABEL_OVERLAY_R3.parquet'
    if target.exists():raise ValueError('OUTPUT_ALREADY_EXISTS_PRESERVE')
    tail.to_parquet(target,index=False,compression='zstd')
    aud=sorted(aud,key=lambda x:x['part']);rep={'status':'LOCAL_LABEL_OVERLAY_COMPLETE_FIT_PENDING','label_identity':IDENT,'source_tail_rows':len(tail),'source_tail_stocks':int(tail.ts_code.nunique()),
      'by_reason':tail.local_label_status.value_counts().to_dict(),'known_label_stocks':int(tail.loc[tail.local_label_status.eq('KNOWN_LOCAL_LABEL'),'ts_code'].nunique()),
      'known_signal_dates':sorted(int(x) for x in tail.loc[tail.local_label_status.eq('KNOWN_LOCAL_LABEL'),'signal_date'].unique()),
      'known_exit_min_max':[int(tail.loc[tail.local_label_status.eq('KNOWN_LOCAL_LABEL'),'local_exit_date'].min()),int(tail.loc[tail.local_label_status.eq('KNOWN_LOCAL_LABEL'),'local_exit_date'].max())],
      'excluded_retained_codes':sorted(excluded),'all_cloud_original_fields_retained':True,'parent_model_fit_key_overlap':len(overlap),
      'calendar':'OBSERVED_PANEL_SESSION_PROXY_UNCERTIFIED','cross_source_price_return_equivalence':'CANNOT_CONFIRM','precision_gate':'USER_ACCEPTED_PRECISION_NONBLOCKING; raw values unchanged','PIT':'CANNOT_CONFIRM',
      'input_cloud_sha256':'ec10ffc05beec1ffee27cd3afe1c7e44a54cbeba1f705c6f6e633082a78c0a12','parent_model_sha256':'63c66f90badd425dcc2607fced5b6d378856be5605beb6184204dcca64d20708',
      'local_selector_declared_sha256':co['input']['selector_declared_sha256'],'local_generation':co['input']['generation'],'session_sha256':r.sha(SESSION),
      'overlay_path':str(target),'overlay_sha256':r.sha(target),'cache_parts':aud,'source_groups_read':len(groups),'physical_rows_read':sum(x['physical_rows_read'] for x in aud),
      'selected_price_keys':len(prices),'workers':NWORK,'wall_seconds':round(time.time()-start,3),'peak_rss_bytes':int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}
    (ROOT/'LOCAL_LABEL_OVERLAY_REPORT_R3.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:rep[k] for k in ('status','source_tail_rows','source_tail_stocks','by_reason','known_label_stocks','known_exit_min_max','overlay_sha256','physical_rows_read','workers','wall_seconds','peak_rss_bytes')},ensure_ascii=False))
if __name__=='__main__':main()
