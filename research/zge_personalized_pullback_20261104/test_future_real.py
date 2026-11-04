"""Non-vacuous future perturbation on the three real canary securities."""
import json
import pandas as pd
from pipeline import OUT, GLOBAL, PERSONAL, process_stock

root=OUT/'canary'; result={}
for index in range(3):
    frame=pd.read_parquet(root/f'canary_input_{index:05d}.parquet').sort_values('trade_date').reset_index(drop=True)
    period=frame.loc[frame.trade_date.ge(20210101)]
    cutoff=int(period.trade_date.iloc[int(len(period)*.7)])
    original,_,_=process_stock(frame);changed=frame.copy();mask=changed.trade_date.gt(cutoff)
    for col in ['open','high','low','close','volume']:changed.loc[mask,col]=pd.to_numeric(changed.loc[mask,col],errors='coerce')*2
    for col in ['J','zge_white_line','zge_yellow_line','BBI','macd_hist']:changed.loc[mask,col]=9999
    altered,_,_=process_stock(changed)
    cols=['ts_code','trade_date','anchor_date','event_group','anchor_key','anchor_wave']+GLOBAL+PERSONAL
    a=pd.DataFrame(original).reindex(columns=cols);b=pd.DataFrame(altered).reindex(columns=cols)
    a=a.loc[a.trade_date.le(cutoff)].reset_index(drop=True);b=b.loc[b.trade_date.le(cutoff)].reset_index(drop=True)
    if len(a)==0:raise AssertionError('NO_REAL_EVENTS_BEFORE_CUTOFF')
    pd.testing.assert_frame_equal(a,b,check_dtype=False)
    result[str(frame.ts_code.iloc[0])]={'cutoff':cutoff,'events_compared':len(a),'past_features_and_event_identity':'PASS'}
(root/'NONVACUOUS_FUTURE_CHECKS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
