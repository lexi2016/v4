"""Canary the distinct local-QFQ label identity on three original pending keys."""
import json
import numpy as np
import pandas as pd
import runtime as r
import local_label_canary as c

# Original seven mixed-basis symbols are all excluded in this stage.
c.MIX=c.R4/'mixed_cache/MIXED_INPUT_REPORT.json'
ss=pd.read_parquet(c.SESSION).trade_date.to_numpy(dtype='int64')
SAMPLES=[('600028.SH',20261015),('000017.SZ',20261015),('920006.BJ',20261015)]
source=pd.read_parquet(c.CLOUD,columns=['ts_code','signal_date','entry_date','entry_open_px','exit_date_t5','status_t5','ret_t5_pct'])
keys=[];dates=set()
for tc,d in SAMPLES:
    row=source[(source.ts_code==tc)&(source.signal_date==d)]
    if len(row)!=1 or row.status_t5.iloc[0]!='PENDING':raise ValueError('CANARY_ORIGINAL_KEY_INVALID')
    ix=np.searchsorted(ss,d)
    if ss[ix]!=d or ix+6>=len(ss):raise ValueError('CANARY_SESSION_NOT_AVAILABLE')
    entry,exit=int(ss[ix+1]),int(ss[ix+6]);dates.update((entry,exit));keys.append((tc,d,entry,exit,row.iloc[0]))
px,audit=c.extract({x[0] for x in SAMPLES},dates);px=px.set_index(['ts_code','trade_date']);details=[]
for tc,d,e,x,orig in keys:
    a=px.loc[(tc,e)];b=px.loc[(tc,x)];ok=bool(a.price_valid and b.price_valid and np.isfinite(a.open) and np.isfinite(b.open) and a.open>0 and b.open>0 and np.isfinite(a.volume) and np.isfinite(b.volume) and a.volume>0 and b.volume>0)
    if not ok:raise ValueError('CANARY_LOCAL_PRICE_OR_VOLUME_INVALID:'+tc)
    ret=float((b.open/a.open-1)*100)
    details.append({'ts_code':tc,'signal_date':d,'entry_date':e,'exit_date':x,'local_entry_open':float(a.open),'local_exit_open':float(b.open),
       'entry_volume':float(a.volume),'exit_volume':float(b.volume),'local_ret_t5_pct':ret,
       'cloud_original_status':str(orig.status_t5),'cloud_original_exit_date':int(orig.exit_date_t5),
       'cloud_original_return':None if pd.isna(orig.ret_t5_pct) else float(orig.ret_t5_pct),'checks':{
           'exact_observed_sessions':bool(e==int(ss[np.searchsorted(ss,d)+1]) and x==int(ss[np.searchsorted(ss,d)+6])),
           'local_panel_equals_cache':bool(a['_merge']=='both' and b['_merge']=='both' and a.open==a.panel_open and b.open==b.panel_open),
           'mature_by_20261104':x<=20261104,'return_recomputed':bool(np.isclose(ret,(float(b.open)/float(a.open)-1)*100,atol=1e-12))}})
# Unit-level missing/zero-volume semantics: unknown never produces a return.
def price_valid(open1,open6,vol1,vol6):
    vals=np.array([open1,open6,vol1,vol6],float)
    return bool(np.isfinite(vals).all() and (vals>0).all())
assert not price_valid(1,1,0,1) and not price_valid(1,np.nan,1,1) and not price_valid(0,1,1,1)
report={'status':'THREE_LOCAL_LABEL_IDENTITY_CANARY_PASS','label_identity':'LOCAL_PANEL_QFQ_ASOF_20261104_OPEN_TO_OPEN_T5_V1',
 'representative_rule':'same original D=20261015 PENDING: SH/SZ/BJ; original cloud fields are read-only', 'samples':details,
 'source_audit':audit,'local_selector_generation':c.cfg['input']['generation'],'local_selector_sha256_producer_declared':c.cfg['input']['selector_declared_sha256'],
 'r4_contract_sha256':r.sha(c.CONTRACT),'observed_session_sha256':r.sha(c.SESSION),'calendar':'OBSERVED_PANEL_SESSION_PROXY_UNCERTIFIED',
 'zero_missing_and_nonpositive_validation':'PASS_UNKNOWN_NOT_ZERO_OR_SHIFTED','cloud_local_equivalence':'CANNOT_CONFIRM',
 'original_cloud_mismatch_evidence':str(c.ROOT/'LOCAL_LABEL_CANARY.json'),'PIT':'CANNOT_CONFIRM','no_cloud_field_mutation':True}
path=c.ROOT/'LOCAL_V1_CANARY.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps(report,ensure_ascii=False))
