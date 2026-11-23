import numpy as np
import pandas as pd
from ops.pft_act010_scan import scan_security,natural_masks,infer
from ops.pft_act008_b_features import b_frame


def history(n=80):
    return pd.DataFrame({'trade_date':pd.bdate_range('2026-01-01',periods=n).strftime('%Y%m%d'),
        'ts_code':'000001.SZ','open':10.,'high':10.2,'low':9.8,'close':10.,'vol':100.,
        'bbi':10.1,'zge_white_line':9.9,'zge_yellow_line':9.5,'kdj_k':20.,'kdj_d':23.,
        'kdj_j':14.,'tradeable_basic':1.,'user_v1_B1':0.,'user_v1_B2':0.,'user_v1_B3':0.})


def test_natural_unknown_and_all_dates_no_quota():
    h=history();h['user_v1_B1']=np.nan
    rows,vectors,_=scan_security(('000001.SZ',{'000001.SZ':h.to_dict('records')},[]))
    b1=[r for r in rows if r['lane']=='B1']
    assert len(b1)==20 and all(np.isnan(r['original']) for r in b1)
    assert all(np.isnan(r['label']) for r in b1)
    assert len(vectors)==20


def test_raw_short_warmup_survives_but_untradeable_d_does_not():
    h=history(10);h['user_v1_B1']=1.
    h.loc[8,'tradeable_basic']=0
    rows,_,_=scan_security(('000001.SZ',{'000001.SZ':h.to_dict('records')},[]))
    assert len(rows)==9 and all(r['raw_trigger'] and not r['eligible'] for r in rows)
    assert h.loc[8,'trade_date'] not in {r['D'] for r in rows}


def test_near_uses_observed_three_j_and_previous_vr5():
    h=history();h.loc[77,'kdj_j']=np.nan;h.loc[79,['close','high','vol']]=[10.3,10.4,120]
    b=b_frame(h);raw,near=natural_masks(h,b)['B2']
    assert not near.iloc[79]


def test_full_frame_matches_prefix_and_future_mutation():
    h=history();h.loc[65:70,'user_v1_B1']=1.
    all_rows,all_vectors,_=scan_security(('000001.SZ',{'000001.SZ':h.to_dict('records')},[]))
    prefix=h.iloc[:71]
    rows,vectors,_=scan_security(('000001.SZ',{'000001.SZ':prefix.to_dict('records')},[]))
    pd.testing.assert_frame_equal(pd.DataFrame(rows),pd.DataFrame([r for r in all_rows if r['D']<=prefix.iloc[-1].trade_date]))
    pd.testing.assert_frame_equal(pd.DataFrame(vectors),pd.DataFrame([r for r in all_vectors if r['D']<=prefix.iloc[-1].trade_date]))
