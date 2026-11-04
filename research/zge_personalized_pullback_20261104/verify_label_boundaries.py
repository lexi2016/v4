"""Check all cached label dates and persist horizon-specific availability."""
import json
import numpy as np
import pandas as pd
from pipeline import OUT, assign_labels, atomic_json, sha, write_parquet_atomic

root=OUT/'r3/full';ev=pd.read_parquet(root/'events_features_labels.parquet')
sessions=pd.read_parquet(root/'observed_a_sessions.parquet').trade_date.to_numpy(dtype='int64')
pos=pd.Index(sessions).get_indexer(ev.trade_date.astype('int64'));assert (pos>=0).all()
out={'scope':'ALL_R3_EVENTS_AND_REAL_LAST_TEN_OBSERVED_PANEL_SESSIONS','event_rows':len(ev),'last_ten_sessions':sessions[-10:].tolist(),'horizons':{}}
for n in [1,5,10]:
    indices=pos+n; expected=np.full(len(indices),-1,dtype='int64');mature=indices<len(sessions);expected[mature]=sessions[indices[mature]]
    actual=ev[f'date_d{n}'].to_numpy(dtype='int64');assert np.array_equal(expected,actual)
    if n in (5,10):assert ev.loc[~mature,f'y{n}'].eq(-1).all()
    out['horizons'][f'd{n}']={'unmatured_rows':int((~mature).sum()),'wrong_date_count':int((expected!=actual).sum()),
        'unmatured_known_count':None if n==1 else int(ev.loc[~mature,f'y{n}'].ge(0).sum())}

# Preserve detailed missing/invalid/unmatured causes without changing y or fit.
status=pd.DataFrame({'ts_code':ev.ts_code,'trade_date':ev.trade_date})
entry_missing=ev.open_d1.isna();entry_invalid=~ev.entry_price_valid.fillna(False).astype(bool)
status['d1_status']=np.select([ev.date_d1.lt(0),entry_missing,entry_invalid],['UNMATURED_D1','UNKNOWN_MISSING_D1','UNKNOWN_INVALID_D1'],default='KNOWN_D1')
for n in (5,10):
    status[f'd{n}_status']=np.select([ev[f'date_d{n}'].lt(0),ev.date_d1.lt(0),entry_missing,entry_invalid,
        ev[f'close_d{n}'].isna(),~ev[f'target{n}_price_valid'].fillna(False).astype(bool)],
        [f'UNMATURED_D{n}','UNMATURED_D1','UNKNOWN_MISSING_D1','UNKNOWN_INVALID_D1',f'UNKNOWN_MISSING_D{n}',f'UNKNOWN_INVALID_D{n}'],default='KNOWN')
    assert np.array_equal(status[f'd{n}_status'].eq('KNOWN').to_numpy(),ev[f'y{n}'].ge(0).to_numpy())
    out['horizons'][f'd{n}']['availability_counts']={str(k):int(v) for k,v in status[f'd{n}_status'].value_counts().items()}

# Separate real-code-path synthetic cases: missing entry, missing D5, missing D10,
# and a fully observed control. No shift to the next stock row is permissible.
cal=np.arange(20220101,20220116,dtype='int64');stocks=['000001.SZ','000002.SZ','000003.SZ','000004.SZ']
signals=pd.DataFrame({'ts_code':stocks,'trade_date':[int(cal[0])]*4});rows=[]
for k,stock in enumerate(stocks):
    for i,day in enumerate(cal):
        if (k==0 and i==1) or (k==1 and i==5) or (k==2 and i==10):continue
        rows.append({'ts_code':stock,'trade_date':int(day),'open':10.,'close':11.,'price_valid':True})
x=assign_labels(signals,pd.DataFrame(rows),cal)
assert list(x.y5)==[-1,-1,1,1] and list(x.y10)==[-1,1,-1,1]
assert list(x.date_d1)==[cal[1]]*4 and list(x.date_d5)==[cal[5]]*4 and list(x.date_d10)==[cal[10]]*4
out['synthetic_missing_cases']={'D1_missing':'PASS','D5_missing':'PASS','D10_missing':'PASS','all_present':'PASS','cross_stock':'PASS'}
path=root/'label_status_overlay.parquet';write_parquet_atomic(status,path)
out['status_overlay_path']=str(path);out['status_overlay_sha256']=sha(path)
atomic_json(root/'LABEL_BOUNDARY_TESTS.json',out);print(json.dumps(out,ensure_ascii=False))
