"""Causal ACT-008 B inputs and operational weak labels, not source gold.

Direct V4 K/D/J and original indicator columns are required. No KDJ is
recomputed here. S fields, original booleans and labels are never B inputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LANES = ('B1', 'B2', 'B3')
BASE_FEATURES = (
    'ret1_pct', 'ret2_pct', 'ret5_pct', 'ret10_pct', 'range_pct',
    'body_pct', 'upper_wick_pct', 'lower_wick_pct', 'close_location',
    'gap_pct', 'volume_ratio1', 'volume_ratio4', 'volume_ratio5', 'volume_ratio20',
    'previous_ret_pct', 'previous_volume_ratio5', 'kdj_k', 'kdj_d', 'kdj_j',
    'j_lag1', 'j_lag2', 'j_change', 'k_change', 'close_vs_ma5_pct',
    'close_vs_ma20_pct', 'position60_pct', 'close_vs_prior20_high_pct',
    'low_slope5_pct', 'range5_mean_pct',
)
BRANCH_FEATURES = (
    'wy_spread_pct', 'c_vs_white_pct', 'c_vs_yellow_pct',
    'y_consec2_active_5b', 'repaired_prior_y_break', 'recent_anchor_low_intact',
    'c_vs_recent_anchor_low_pct', 'c_vs_recent_anchor_mid_pct',
    'pb_affinity', 'ra_affinity',
)
FULL_FEATURES = (*BASE_FEATURES, 'S_probability', *(f'S_{name}' for name in BRANCH_FEATURES))
DIRECT_FIELDS = ('kdj_k', 'kdj_d', 'kdj_j', 'user_v1_B1', 'user_v1_B2', 'user_v1_B3', 'tradeable_basic')


def _bool_numeric(series: pd.Series) -> pd.Series:
    """Accept numeric/bool representations; missing or malformed stays UNKNOWN."""
    replaced = series.replace({'TRUE': 1, 'FALSE': 0, 'True': 1, 'False': 0, 'true': 1, 'false': 0})
    result = pd.to_numeric(replaced, errors='coerce').astype(float)
    return result.where(result.isin([0., 1.]))


def b_frame(history: pd.DataFrame) -> pd.DataFrame:
    required = ('trade_date', 'open', 'high', 'low', 'close', 'vol', 'bbi',
                'zge_white_line', 'zge_yellow_line', *DIRECT_FIELDS)
    missing = set(required) - set(history)
    if missing:
        raise ValueError('B_REQUIRED_FIELDS_MISSING:' + ','.join(sorted(missing)))
    h = history.loc[:, required].sort_values('trade_date', kind='mergesort').reset_index(drop=True).copy()
    if h.trade_date.duplicated().any():
        raise ValueError('DUPLICATE_CANONICAL_TRADE_DATE')
    for name in required[1:]:
        h[name] = _bool_numeric(h[name]) if name.startswith('user_v1_') or name == 'tradeable_basic' else pd.to_numeric(h[name], errors='coerce').astype(float)
    o, hi, lo, c, v, w, y, j = (h[name] for name in ('open', 'high', 'low', 'close', 'vol', 'zge_white_line', 'zge_yellow_line', 'kdj_j'))
    prev = c.shift(1)
    r = (c / prev - 1) * 100
    vr5 = v / v.shift(1).rolling(5, min_periods=5).mean().replace(0, np.nan)
    vr1 = v / v.shift(1).replace(0, np.nan)
    amp = (hi - lo) / prev * 100
    wick = (hi - pd.concat([o, c], axis=1).max(axis=1)) / prev * 100
    loc = ((c - lo) / (hi - lo)).where(hi.gt(lo), .5)
    pre5lo, pre5hi = lo.shift(1).rolling(5).min(), hi.shift(1).rolling(5).max()
    pre3hi = hi.shift(1).rolling(3).max()
    prior_break_hi = hi.shift(2).rolling(5).max()
    previous_mid = (o.shift(1) + c.shift(1)) / 2
    ma5, ma20 = c.rolling(5).mean(), c.rolling(20).mean()
    hi60, lo60 = hi.rolling(60).max(), lo.rolling(60).min()
    inputs = pd.DataFrame({
        'ret1_pct': r, 'ret2_pct': c.pct_change(2, fill_method=None) * 100,
        'ret5_pct': c.pct_change(5, fill_method=None) * 100, 'ret10_pct': c.pct_change(10, fill_method=None) * 100,
        'range_pct': amp, 'body_pct': (c-o)/prev*100, 'upper_wick_pct': wick,
        'lower_wick_pct': (pd.concat([o,c],axis=1).min(axis=1)-lo)/prev*100,
        'close_location': loc, 'gap_pct': (o/prev-1)*100,
        'volume_ratio1': vr1, 'volume_ratio4': v/v.shift(1).rolling(4).mean().replace(0,np.nan),
        'volume_ratio5': vr5, 'volume_ratio20': v/v.shift(1).rolling(20).mean().replace(0,np.nan),
        'previous_ret_pct': r.shift(1), 'previous_volume_ratio5': vr5.shift(1),
        'kdj_k': h.kdj_k, 'kdj_d': h.kdj_d, 'kdj_j': j,
        'j_lag1': j.shift(1), 'j_lag2': j.shift(2), 'j_change': j-j.shift(1),
        'k_change': h.kdj_k-h.kdj_k.shift(1), 'close_vs_ma5_pct': (c/ma5-1)*100,
        'close_vs_ma20_pct': (c/ma20-1)*100,
        'position60_pct': ((c-lo60)/(hi60-lo60)*100).where(hi60.gt(lo60),50),
        'close_vs_prior20_high_pct': (c/hi.shift(1).rolling(20).max()-1)*100,
        'low_slope5_pct': (lo/lo.shift(4)-1)*100, 'range5_mean_pct': amp.rolling(5).mean(),
    })
    # Explicit data-observation masks prevent pandas comparisons turning NaN
    # into FALSE, including rolling COUNT and yesterday volume predicates.
    known = h[['open','high','low','close','vol','bbi','zge_white_line','zge_yellow_line','kdj_k','kdj_d','kdj_j']].notna().all(axis=1)
    valid = known & h.tradeable_basic.eq(1) & v.gt(0) & pd.concat([o,hi,lo,c,w,y,h.bbi],axis=1).gt(0).all(axis=1)
    valid &= hi.ge(pd.concat([o,c,lo],axis=1).max(axis=1)) & lo.le(pd.concat([o,c,hi],axis=1).min(axis=1))
    valid &= np.arange(len(h)) >= 60
    original_known = {
        'B1': known,
        'B2': known & j.rolling(3).count().eq(3) & v.shift(1).rolling(4).count().eq(4) & prev.notna(),
        'B3': known & j.shift(2).notna() & v.shift(2).rolling(4).count().eq(4) & r.shift(1).notna() & vr1.notna(),
    }
    original = {
        'B1': h.bbi.gt(w) & w.gt(y) & j.le(13),
        'B2': j.rolling(3).min().lt(13) & v.gt(v.shift(1).rolling(4).mean()*1.25) & r.gt(4) & j.lt(70) & w.gt(y),
        'B3': j.shift(2).lt(20) & v.shift(1).gt(v.shift(2).rolling(4).mean()*1.15) & r.shift(1).gt(3) & w.gt(y) & (r.gt(0) | (r.gt(-3) & (vr1.lt(.6) | vr1.gt(.9)))),
    }
    candidates = {
        'B1': w.gt(y) & j.le(28),
        'B2': w.gt(y) & j.rolling(3).min().le(24) & r.ge(2.5) & vr5.ge(1.05),
        'B3': w.gt(y) & j.shift(2).lt(30) & r.shift(1).ge(2) & vr5.shift(1).ge(1.05),
    }
    positive = {
        'B1': w.gt(y) & j.le(24) & w.ge(w.shift(5)) & c.ge(y) & c.ge(.995*pre5lo) & lo.ge(.98*pre5lo) & r.between(-3.5,2.5) & vr5.le(.90) & amp.le(6.5),
        'B2': w.gt(y) & c.gt(w) & c.gt(y) & r.ge(2.5) & vr5.ge(1.15) & j.gt(j.shift(1)) & c.gt(pre3hi) & loc.ge(.65) & wick.le(4) & (pre5hi/pre5lo-1).le(.16) & j.rolling(5).min().le(24),
        'B3': w.gt(y) & j.shift(2).lt(30) & r.shift(1).ge(2.5) & vr5.shift(1).ge(1.05) & c.shift(1).gt(prior_break_hi) & lo.ge(.98*lo.shift(1)) & c.ge(previous_mid) & c.ge(y) & r.between(-2.5,6) & amp.le(8) & (vr1.le(1.20) | (r.ge(1.5) & loc.ge(.65))),
    }
    adverse = {
        'B1': c.lt(y) | c.lt(.99*pre5lo) | (vr5.ge(1.25) & r.le(-2.5)),
        'B2': c.le(y) | c.le(pre3hi) | (loc.lt(.55) & wick.gt(2.5)) | (amp.ge(8) & (c/hi.rolling(30).max()-1).le(-.20)),
        'B3': c.lt(previous_mid) | lo.lt(.98*lo.shift(1)) | (c.shift(1).le(prior_break_hi) & c.lt(w)) | (r.le(-2) & vr1.ge(1.20)),
    }
    # Every operand of both positive and adverse branches must be observed.
    # Otherwise a missing positive operand could erase a conflict and turn an
    # UNKNOWN row into an apparently proven negative.
    operands = {
        'B1': [pre5lo,r,vr5,amp,w.shift(5)],
        'B2': [pre5lo,pre5hi,pre3hi,r,vr5,j.shift(1),j.rolling(5).min(),
               loc,wick,amp,hi.rolling(30).max()],
        'B3': [previous_mid,lo.shift(1),prior_break_hi,r,vr1,amp,loc,
               r.shift(1),vr5.shift(1),j.shift(2)],
    }
    label_known = {lane: valid & pd.concat(values,axis=1).notna().all(axis=1)
                   for lane,values in operands.items()}
    result = inputs.loc[:, BASE_FEATURES].copy()
    result.insert(0, 'trade_date', h.trade_date.astype(str))
    result['eligible'] = valid
    for lane in LANES:
        orig = original[lane].astype(float).where(original_known[lane], np.nan)
        result[f'{lane}_original'] = h[f'user_v1_{lane}']
        result[f'{lane}_recomputed'] = orig
        result[f'{lane}_formula_mismatch'] = orig.notna() & h[f'user_v1_{lane}'].notna() & orig.ne(h[f'user_v1_{lane}'])
        candidate = (candidates[lane] | orig.eq(1)) & label_known[lane] & orig.notna() & h[f'user_v1_{lane}'].notna()
        pos, neg = positive[lane], adverse[lane]
        label = pd.Series(np.nan, index=h.index)
        label.loc[candidate & pos & ~neg] = 1.
        label.loc[candidate & neg & ~pos] = 0.
        result[f'{lane}_label'] = label
        result[f'{lane}_reason'] = np.select([candidate & pos & neg, label.eq(1), label.eq(0)], ['CONFLICT_UNKNOWN','INDEPENDENT_D_CONFIRM','INDEPENDENT_D_ADVERSE'], default='UNPROVEN_UNKNOWN')
        result[f'{lane}_stratum'] = np.select([label.eq(1), label.eq(0) & orig.eq(1), label.eq(0) & orig.eq(0)], ['POSITIVE','HARD_ORIGINAL_ADVERSE','NEAR_MISS_ADVERSE'], default='UNKNOWN')
    result['B2_1006_r_ge4'] = r.ge(4).astype(float).where(r.notna())
    result['B2_1006_j_lt55'] = j.lt(55).astype(float).where(j.notna())
    result['B2_1006_volume_gt_prior'] = vr1.gt(1).astype(float).where(vr1.notna())
    result['B2_1006_j_rising'] = j.gt(j.shift(1)).astype(float).where(j.notna() & j.shift(1).notna())
    result['B2_1006_full'] = 'UNKNOWN'
    result['B2_151_volume_ratio_ge1_20'] = vr1.ge(1.2).astype(float).where(vr1.notna())
    result['B2_151_full'] = 'UNKNOWN'
    return result.replace([np.inf,-np.inf],np.nan)


def frozen_s_gate(row) -> tuple[float, str]:
    """Remove only legacy >=35 gate, retaining G1 and both G2 branches."""
    names = ('wy_spread_pct','c_vs_yellow_pct','d_upper_shadow_pct','d_vr5','dd_from_pk30_pct','d_amp_pct')
    try:
        wy, cy, wick, vr, dd, amp = [float(row[name]) for name in names]
    except (TypeError,ValueError,KeyError):
        return np.nan, 'INPUT_UNKNOWN'
    if not np.isfinite([wy,cy,wick,vr,dd,amp]).all():
        return np.nan, 'INPUT_UNKNOWN'
    reasons=[]
    if wy <= 0: reasons.append('G1_WHITE_NOT_ABOVE_YELLOW')
    if cy >= 25 and wick >= 4 and vr >= 1.5: reasons.append('G2_DISTRIBUTION_GE_25')
    if dd <= -22 and amp >= 8: reasons.append('G2_DRAWDOWN_RANGE')
    return float(not reasons), '|'.join(reasons) or 'PASS'
