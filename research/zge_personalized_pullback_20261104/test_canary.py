"""Bounded real-input perturbation plus synthetic cross-stock/label checks."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from pipeline import OUT, PERSONAL, GLOBAL, process_stock, assign_labels, rank_prior

root=OUT/'canary'; checks={}
for p in sorted(root.glob('canary_input_*.parquet')):
    data=pd.read_parquet(p)
    for sym,frame in data.groupby('ts_code',sort=True):
        frame=frame.sort_values('trade_date').reset_index(drop=True)
        if len(frame)<100:continue
        cutoff=int(frame.trade_date.iloc[int(len(frame)*.7)])
        one,_,_=process_stock(frame); changed=frame.copy(); after=changed.trade_date.gt(cutoff)
        for c in ['open','high','low','close','volume']:changed.loc[after,c]=pd.to_numeric(changed.loc[after,c],errors='coerce')*2
        for c in ['J','zge_white_line','zge_yellow_line','BBI','macd_hist']:changed.loc[after,c]=9999
        two,_,_=process_stock(changed)
        cols=['ts_code','trade_date','anchor_date','event_group','anchor_key','anchor_wave']+GLOBAL+PERSONAL
        a=pd.DataFrame(one).reindex(columns=cols);b=pd.DataFrame(two).reindex(columns=cols)
        a=a.loc[a.trade_date.le(cutoff)].reset_index(drop=True);b=b.loc[b.trade_date.le(cutoff)].reset_index(drop=True)
        pd.testing.assert_frame_equal(a,b,check_dtype=False)
        checks[str(sym)]={'future_perturbation':'PASS','cutoff':cutoff,'events_compared':len(a),'rows':len(frame)}
if len(checks)<3:raise AssertionError('FEWER_THAN_THREE_REAL_STOCK_PERTURBATION_TESTS')

# Two securities share the calendar; the first has no D+1 quote but has D+2.
# Label join must not slide forward to its next stock row, and cannot cross stocks.
sessions=np.arange(20220101,20220113,dtype='int64')
ev=pd.DataFrame({'ts_code':['000001.SZ','000002.SZ'],'trade_date':[int(sessions[0])]*2})
px=[]
for sym in ['000001.SZ','000002.SZ']:
    for i,d in enumerate(sessions):
        if sym=='000001.SZ' and i==1:continue
        px.append({'ts_code':sym,'trade_date':int(d),'open':10.,'close':11.,'price_valid':True})
labelled=assign_labels(ev,pd.DataFrame(px),sessions)
assert labelled.loc[0,'date_d1']==sessions[1] and labelled.loc[0,'y10']==-1
assert labelled.loc[1,'y10']==1 and abs(labelled.loc[1,'R10']-.1)<1e-12
assert labelled.loc[0,'date_d10']==sessions[10]
checks['synthetic_missing_d1_and_cross_stock']='PASS'
series=pd.Series(np.arange(300,dtype=float)); rank=rank_prior(series)
assert rank.iloc[249]==1 and rank.iloc[250]==1
checks['prior_only_rank_extreme']='PASS'
(root/'CANARY_CHECKS.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(checks,ensure_ascii=False))
