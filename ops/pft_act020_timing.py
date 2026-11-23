"""ACT020 prior-year expanding V2 timing. No execution outcomes or fits."""
from __future__ import annotations
import numpy as np
import pandas as pd


def crowd_percentiles(counts):
    """Inclusive empirical CDF, current plus up to 39 preceding available days."""
    values = np.asarray(counts, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError('INVALID_NATURAL_COUNTS')
    return np.array([.5 if i < 9 else np.mean(values[max(0, i-39):i+1] <= v)
                     for i, v in enumerate(values)])


def level_and_brakes(breadth, slope, liquidity, crowd, q33, q67, q20, q25):
    """q33 equality neutral, q67 equality strong; any brakes downgrade only once."""
    if not np.isfinite([breadth, q33, q67, q20, q25]).all():
        return -1, -1, False, False, False
    base = 2 if breadth >= q67 else 1 if breadth >= q33 else 0
    b1 = bool(np.isfinite(slope) and slope < q20)
    b2 = bool(np.isfinite(liquidity) and liquidity < q25 and slope < 0)
    b3 = bool(np.isfinite(crowd) and crowd > .80 and slope < 0)
    return base, max(0, base-int(b1 or b2 or b3)), b1, b2, b3


def timing_daily(market, natural_counts):
    f = market.sort_values('D', kind='mergesort').reset_index(drop=True).copy()
    if f.D.duplicated().any() or not f.D.between('20220101', '20261120').all():
        raise ValueError('MARKET_DATE_DRIFT')
    shares = f[['cw_share', 'cy_share', 'wy_share']]
    f['B_comp'] = shares.mean(axis=1).where(np.isfinite(shares).all(axis=1))
    f['B_slope_5d'] = f.B_comp-f.B_comp.shift(5)
    # Preserve the exact sealed market ratio; reject inconsistent finite values.
    ratio = f.amount_MA5/f.amount_MA20
    if not np.allclose(ratio.to_numpy(), f.liquidity_trend.to_numpy(), equal_nan=True, rtol=1e-10, atol=1e-12):
        raise ValueError('SEALED_LIQUIDITY_RATIO_DRIFT')
    counts = natural_counts.copy()
    counts.index = counts.index.astype(str)
    if counts.index.duplicated().any() or not counts.index.to_series().between('20230101','20261120').all():
        raise ValueError('NATURAL_COUNT_DATE_DRIFT')
    expected_days = f.loc[f.D.ge('20230101'), 'D'].tolist()
    if sorted(counts.index) != expected_days:
        raise ValueError('NATURAL_COUNTS_REQUIRE_ALL_940_SESSIONS')
    f['natural_signal_count'] = f.D.map(counts)
    pct = pd.Series(crowd_percentiles(counts.sort_index()), index=counts.sort_index().index)
    f['crowd_pct_40d_all'] = f.D.map(pct)
    f['crowd_available_days'] = f.D.map(pd.Series(np.minimum(np.arange(1,len(counts)+1),40), index=counts.sort_index().index))
    cutoffs = []
    for year in range(2023, 2027):
        prior = f.loc[f.D.ge('20220101') & f.D.lt(f'{year}0101')]
        b, s, liq = [prior[n].dropna().to_numpy(float) for n in ['B_comp','B_slope_5d','liquidity_trend']]
        if len(b) < 242 or not len(s) or not len(liq):
            raise ValueError('INSUFFICIENT_PRIOR_CALIBRATION:'+str(year))
        q33, q67 = np.quantile(b, [1/3, 2/3], method='linear')
        cutoffs.append(dict(year=year, calibration_max_D=prior.D.max(), calibration_days=len(b),
            slope_days=len(s), liquidity_days=len(liq), q33=q33,q67=q67,
            slope_q20=np.quantile(s,.20,method='linear'),liquidity_q25=np.quantile(liq,.25,method='linear')))
    thresholds = pd.DataFrame(cutoffs)
    mapping = thresholds.set_index('year').to_dict('index')
    records = []
    for row in f.to_dict('records'):
        t = mapping.get(int(row['D'][:4]))
        levels = level_and_brakes(row['B_comp'], row['B_slope_5d'], row['liquidity_trend'],
            row['crowd_pct_40d_all'],t['q33'],t['q67'],t['slope_q20'],t['liquidity_q25']) if t else (-1,-1,False,False,False)
        base, v2, b1,b2,b3 = levels
        records.append(dict(**row, base_level=base,v2_level=v2,brake_slope=b1,brake_liquidity=b2,brake_crowd=b3,
            strict_state='UNKNOWN' if v2 < 0 else 'RISK_OFF' if v2 == 0 else 'RISK_ON',
            strict_cap={-1:0.,0:0.,1:.5,2:1.}[v2],daily_K={-1:0,0:0,1:2,2:3}[v2]))
    return pd.DataFrame(records), thresholds
