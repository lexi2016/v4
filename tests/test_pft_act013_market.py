import numpy as np
import pandas as pd
import pytest
from ops.pft_act013_market import fold_a,daily_aggregate,finish_daily


def row(code='000001.SZ',day='20260105',**kw):
    return dict(ts_code=code,trade_date=day,exchange=code[-2:],market_type='BJ' if code.endswith('BJ') else 'A_SHARE',
                close=10.,pre_close=9.,zge_white_line=9.,zge_yellow_line=8.,vol=100.,amount=1000.,tradeable_basic=1,**kw)


def test_denominators_finite_positive_and_no_downside_ratio():
    rows=[row(),row('000002.SZ'),row('000003.SZ'),row('000004.SZ')]
    rows[1].update(close=7.,pre_close=10.,zge_white_line=np.nan)
    rows[2].update(close=np.inf,amount=np.inf)
    rows[3].update(tradeable_basic=0)
    f=finish_daily(daily_aggregate(pd.DataFrame(rows))).iloc[0]
    assert f.observed==3 and f.cw_n==1 and f.cy_n==2 and f.wy_n==2
    assert f.adv==1 and f.dec==1 and f.unch==0 and f.ad_n==2
    assert f.amount==2000 and f.amount_n==2 and f.ad_ratio==1
    assert f.gate=='RISK_OFF' and np.isnan(f.amount_MA5)
    r=finish_daily(daily_aggregate(pd.DataFrame([row()]))).iloc[0]
    assert r.gate=='RISK_ON' and np.isnan(r.ad_ratio)


def test_bse_effective_date_fold_and_historical_universe():
    rows=[row('830001.BJ','20241008'),row('920001.BJ','20241008'),
          row('830001.BJ','20251009'),row('920001.BJ','20251009'),row('000099.SZ','20220104')]
    rows[1]['close']=100;rows[2]['close']=100
    f,c=fold_a(pd.DataFrame(rows),[dict(old='830001.BJ',new='920001.BJ',effective='20251009')])
    assert len(f)==3 and c['alias_rows_folded']==2 and not f.duplicated(['canonical','trade_date']).any()
    assert set(f[f.canonical.eq('920001.BJ')].close)=={10.}
    assert '000099.SZ' in set(f.canonical)


def test_market_prefix_and_unknown_warmup():
    rows=[row(day=d.strftime('%Y%m%d')) for d in pd.bdate_range('20260101',periods=25)]
    rows[0]['zge_yellow_line']=np.nan
    agg=daily_aggregate(pd.DataFrame(rows));full=finish_daily(agg)
    pd.testing.assert_frame_equal(finish_daily(agg.iloc[:22]),full.iloc[:22])
    assert full.iloc[0].gate=='UNKNOWN'
    assert full.amount_MA20.iloc[:19].isna().all() and full.iloc[19].liquidity_trend==1
