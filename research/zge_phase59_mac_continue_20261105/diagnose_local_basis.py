"""Quarantine per-stock cross-source basis conflicts seen in the 3-case canary.

Only existing cloud samples and R4 price checkpoints are read. A recent
three-row match is bounded compatibility evidence, not future-basis or PIT proof.
"""
import json
import numpy as np
import pandas as pd
import runtime as r
from local_label_canary import ROOT,R4,CLOUD,SESSION,PARTS,stats_map

CLOUD_SHA='ec10ffc05beec1ffee27cd3afe1c7e44a54cbeba1f705c6f6e633082a78c0a12'
df=pd.read_parquet(CLOUD,columns=['ts_code','signal_date','entry_date','entry_open_px','exit_date_t5','status_t5','ret_t5_pct'])
if len(df)!=303161 or df.duplicated(['ts_code','signal_date']).any():raise ValueError('SOURCE_KEY_CONFLICT')
tail=df[(df.signal_date>20261008)&df.signal_date.le(20261015)&df.status_t5.eq('PENDING')].copy();codes=set(tail.ts_code)
old=df[df.ts_code.isin(codes)&df.signal_date.le(20261008)&df.status_t5.eq('MATURED')&df.exit_date_t5.le(20261015)&df.entry_date.notna()&df.entry_open_px.notna()&df.ret_t5_pct.notna()].copy()
old=old.sort_values(['ts_code','signal_date'],kind='stable').groupby('ts_code',sort=False).tail(3).copy();old['scope']='THREE_LATEST_MATURED'
known=tail[tail.entry_date.notna()&tail.entry_open_px.notna()].copy();known['scope']='TAIL_EXISTING_ENTRY'
rows=pd.concat([old,known],ignore_index=True);session=pd.read_parquet(SESSION).trade_date.to_numpy(dtype='int64')
D=rows.signal_date.to_numpy(dtype='int64');idx=np.searchsorted(session,D);valid=(idx<len(session))&(session[np.minimum(idx,len(session)-1)]==D)&(idx+6<len(session))
rows['expected_entry']=np.where(valid,session[np.minimum(idx+1,len(session)-1)],-1);rows['expected_exit']=np.where(valid,session[np.minimum(idx+6,len(session)-1)],-1)
needed=rows[['ts_code','expected_entry']].rename(columns={'expected_entry':'trade_date'});needed2=rows.loc[rows.scope.eq('THREE_LATEST_MATURED'),['ts_code','expected_exit']].rename(columns={'expected_exit':'trade_date'});needed=pd.concat([needed,needed2],ignore_index=True).drop_duplicates()
partmap,_=stats_map();parts={int(partmap[c]['part']):partmap[c] for c in codes if c in partmap};pieces=[];input_parts=[]
for i,st in sorted(parts.items()):
    path=PARTS/f'prices_{i:05d}.parquet';digest=r.sha(path)
    if digest!=st['price_sha256']:raise ValueError('CACHE_HASH_MISMATCH:'+str(i))
    subcodes={x['symbol'] for x in st['symbols']} & codes;req=needed[needed.ts_code.isin(subcodes)];p=pd.read_parquet(path,columns=['ts_code','trade_date','open','price_valid'])
    selected=p.merge(req,on=['ts_code','trade_date'],how='inner',validate='one_to_one');pieces.append(selected);input_parts.append({'part':i,'sha256':digest,'matched_rows':len(selected)})
px=pd.concat(pieces,ignore_index=True)
if px.duplicated(['ts_code','trade_date']).any():raise ValueError('PRICE_KEY_CONFLICT')
entry=px.rename(columns={'trade_date':'expected_entry','open':'local_entry','price_valid':'entry_price_valid'})
exit=px.rename(columns={'trade_date':'expected_exit','open':'local_exit','price_valid':'exit_price_valid'})
rows=rows.merge(entry,on=['ts_code','expected_entry'],how='left',validate='many_to_one').merge(exit,on=['ts_code','expected_exit'],how='left',validate='many_to_one')
rows['entry_date_match']=rows.entry_date.eq(rows.expected_entry);rows['exit_date_match']=rows.exit_date_t5.eq(rows.expected_exit)
rows['entry_ok']=rows.entry_price_valid.fillna(False)&np.isfinite(rows.local_entry)&rows.local_entry.gt(0)&np.isclose(rows.entry_open_px,rows.local_entry,rtol=1e-6,atol=1e-6)
inferred=rows.entry_open_px*(1+rows.ret_t5_pct/100.)
rows['exit_ok']=rows.exit_price_valid.fillna(False)&np.isfinite(rows.local_exit)&rows.local_exit.gt(0)&np.isclose(inferred,rows.local_exit,rtol=1e-6,atol=1e-6)
rows['row_ok']=rows.entry_date_match&rows.entry_ok&np.where(rows.scope.eq('THREE_LATEST_MATURED'),rows.exit_date_match&rows.exit_ok,True)
summary=[];excluded=set(json.loads((R4/'EXPERIMENT_CONTRACT_R4.json').read_text())['input']['excluded_retained_history_codes'])
for tc in sorted(codes):
    a=rows[rows.ts_code.eq(tc)];hist=a[a.scope.eq('THREE_LATEST_MATURED')];t=a[a.scope.eq('TAIL_EXISTING_ENTRY')]
    if tc in excluded:status='EXCLUDED_RETAINED_ORIGINAL_BASIS'
    elif tc not in partmap:status='UNKNOWN_R4_STOCK_CACHE_ABSENT'
    elif len(hist)<3:status='UNKNOWN_LT3_HISTORICAL_MATURED_OVERLAPS'
    elif not hist.row_ok.all():status='QUARANTINE_HISTORICAL_DATE_OR_PRICE_MISMATCH'
    elif len(t) and not t.row_ok.all():status='QUARANTINE_KNOWN_TAIL_ENTRY_MISMATCH'
    else:status='RECENT_THREE_PRICE_DATE_MATCH_REPLAY_ONLY'
    summary.append({'ts_code':tc,'status':status,'historical_compared_rows':len(hist),'historical_failed_rows':int((~hist.row_ok).sum()),
                    'known_tail_entries':len(t),'known_tail_entry_failed_rows':int((~t.row_ok).sum()),'tail_signal_rows':int((tail.ts_code==tc).sum())})
out=pd.DataFrame(summary);rp=ROOT/'inputs/LOCAL_BASIS_OVERLAP_ROWS.parquet';rows.to_parquet(rp,index=False,compression='zstd');sp=ROOT/'inputs/LOCAL_BASIS_STOCK_STATUS.parquet';out.to_parquet(sp,index=False,compression='zstd')
report={'status':'BOUNDED_SOURCE_OVERLAP_DIAGNOSTIC_COMPLETE_NOT_PIT','tail_rows':len(tail),'tail_stocks':len(codes),'historical_rows':len(old),
 'tail_cloud_known_entry_rows':len(known),'status_stocks':out.status.value_counts().to_dict(),
 'status_tail_rows':out.groupby('status').tail_signal_rows.sum().to_dict(),'historical_date_entry_exit_matches':int(rows.loc[rows.scope.eq('THREE_LATEST_MATURED'),'row_ok'].sum()),
 'tail_known_entry_matches':int(rows.loc[rows.scope.eq('TAIL_EXISTING_ENTRY'),'row_ok'].sum()),
 'rows_path':str(rp),'rows_sha256':r.sha(rp),'stock_status_path':str(sp),'stock_status_sha256':r.sha(sp),
 'cache_parts_read':len(input_parts),'cache_parts':input_parts,'session_sha256':r.sha(SESSION),'cloud_sha256':CLOUD_SHA,
 'binding_limit':'Exact recent 3 overlap and known tail entries are a bounded compatibility screen, not proof of later price equivalence, PIT or authoritative calendar.',
 'basis_600028':'source numerical discrepancy retained; cause and cross-asof factor CANNOT_CONFIRM; no rounding'}
(ROOT/'LOCAL_BASIS_DIAGNOSIS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps({k:report[k] for k in ['status','tail_rows','tail_stocks','historical_rows','tail_cloud_known_entry_rows','status_stocks','status_tail_rows','rows_sha256','stock_status_sha256']},ensure_ascii=False))
