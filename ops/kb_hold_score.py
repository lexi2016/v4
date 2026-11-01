"""Knowledge-body five-part holding-score projection for one ordered A-share.

Unquantified volume branches remain unknown; N is applied only when bound.
This module does not change the 57 KB fields or issue trading instructions.
"""
from __future__ import annotations

import math


COMPONENTS = ('kb_hold_close_up', 'kb_hold_above_bbi', 'kb_hold_volume_ok',
              'kb_hold_trend_up', 'kb_hold_j_not_dead')
SINGLE_STOCKS = frozenset({'002865.SZ', '301048.SZ'})
SUPPLEMENTAL_REASONS = {
    'kb_s1': 'SOURCE_VERSION_CONFLICT_AND_UNQUANTIFIED',
    'kb_s2': 'S1_ANCHOR_AND_RULE_UNCONFIRMED',
    'kb_s3': 'S1_S2_ANCHOR_AND_RULE_UNCONFIRMED',
    'kb_didi_1455': 'BOUND_1455_MINUTE_INPUT_UNAVAILABLE',
}


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def volume_component(source):
    """The existing, confirmed positive-candle branch; other branches stay unknown."""
    open_, close, high, low, volume = (_number(source.get(key)) for key in ('open', 'close', 'high', 'low', 'volume'))
    valid_hlc = close is not None and high is not None and low is not None and low <= close <= high
    valid_ohlc = valid_hlc and open_ is not None and low <= open_ <= high
    value = True if valid_ohlc and volume is not None and close > open_ else None
    reason = (None if value is True else 'INVALID_OHLC_INPUT' if not valid_ohlc else
              'INVALID_VOLUME_INPUT' if volume is None else 'RULE_NOT_QUANTIFIED')
    return value, reason


def score_history(rows):
    """Score the supplied prefix once, preserving missing/invalid inputs.

    BBI and KDJ follow the pinned KB core indicator initialization/rounding;
    insufficient histories do not inherit its default numeric values. J below
    both K and D is the dead-cross *state*, not only the crossing instant.
    """
    result = []
    closes, highs, lows = [], [], []
    previous_date = 0
    k = d = 50.0
    kdj_prefix_valid = True
    for source in rows:
        date = int(source['trade_date'])
        if date <= previous_date:
            raise ValueError('HOLD_SCORE_DATES_NOT_UNIQUE_SORTED')
        previous_date = date
        open_, close, high, low, volume = (_number(source.get(key)) for key in ('open', 'close', 'high', 'low', 'volume'))
        valid_hlc = close is not None and high is not None and low is not None and low <= close <= high
        valid_ohlc = valid_hlc and open_ is not None and low <= open_ <= high
        closes.append(close)
        highs.append(high)
        lows.append(low)
        kdj_prefix_valid = kdj_prefix_valid and valid_hlc
        n = len(closes)
        close_up = close > closes[-2] if n >= 2 and close is not None and closes[-2] is not None else None
        bbi = None
        above_bbi = None
        if n >= 24 and all(value is not None for value in closes[-24:]):
            bbi = round(sum(sum(closes[-period:]) / period for period in (3, 6, 12, 24)) / 4, 2)
            # "above BBI" and "not broken" disagree exactly at equality.
            above_bbi = None if close == bbi else close > bbi
        k_value = d_value = j_value = j_not_dead = None
        if n >= 9 and kdj_prefix_valid:
            low9, high9 = min(lows[-9:]), max(highs[-9:])
            rsv = 50.0 if high9 == low9 else (close - low9) / (high9 - low9) * 100
            k = (2 / 3) * k + (1 / 3) * rsv
            d = (2 / 3) * d + (1 / 3) * k
            k_value, d_value, j_value = round(k, 2), round(d, 2), round(3 * k - 2 * d, 2)
            j_not_dead = not (j_value < k_value and j_value < d_value)
        # The knowledge-body rule explicitly awards 阳量; a valid up candle
        # establishes that branch without guessing a subjective volume limit.
        # A down or flat candle alone cannot decide the remaining branches.
        volume_ok, volume_reason = volume_component(source)
        components = (close_up, above_bbi, volume_ok, None, j_not_dead)
        lower = sum(value is True for value in components)
        unknown = sum(value is None for value in components)
        row = dict(zip(COMPONENTS, components))
        close_reason = ('INSUFFICIENT_PRIOR_BAR' if n < 2 else 'INVALID_CLOSE_INPUT') if close_up is None else None
        bbi_reason = ('INSUFFICIENT_BBI_HISTORY' if n < 24 else
                      'INVALID_CLOSE_WINDOW' if bbi is None else 'BBI_EQUALITY_UNRESOLVED') if above_bbi is None else None
        j_reason = ('INSUFFICIENT_KDJ_HISTORY' if n < 9 else 'INVALID_HLC_PREFIX') if j_not_dead is None else None
        row.update(kb_hold_score=lower if unknown == 0 else None,
                   kb_hold_score_min=lower, kb_hold_score_max=lower + unknown,
                   kb_hold_score_status='COMPLETE' if unknown == 0 else 'PARTIAL_UNKNOWN',
                   kb_hold_bbi=bbi, kb_hold_k=k_value, kb_hold_d=d_value, kb_hold_j=j_value,
                   kb_hold_close_up_reason=close_reason, kb_hold_above_bbi_reason=bbi_reason,
                   kb_hold_volume_ok_reason=volume_reason,
                   kb_hold_trend_up_reason='RULE_NOT_QUANTIFIED',
                   kb_hold_j_not_dead_reason=j_reason)
        result.append(row)
    return result


def project_single_history(code, rows):
    """Append-only single-stock daily projection on the bound QFQ prefix.

    Revision must pass the revised complete prefix so the same authority is
    used for a fresh build, next day, and correction. It does not obtain bars,
    select a pool, change pointers, or compute any of the accepted 57 fields.
    """
    if code not in SINGLE_STOCKS:
        raise ValueError('SINGLE_STOCK_SCOPE_CONFLICT')
    output = score_history(rows)
    for source, row in zip(rows, output):
        if 'kb_b1_j' not in source:
            raise ValueError('BOUND_KB_J_MISSING')
        existing = source['kb_b1_j']
        if existing is not None and isinstance(existing, float) and math.isnan(existing):
            existing = None
        if existing != row['kb_hold_j']:
            raise ValueError('BOUND_KB_J_MISMATCH')
        # Identical J already has its own immutable KB column; do not copy it.
        del row['kb_hold_j']
        for field, reason in SUPPLEMENTAL_REASONS.items():
            row[field] = None
    return output


def apply_n_score(code, source_rows, score_rows, n_rows, *, rule_sha256, helper_sha256, allowed_symbols=None):
    """Update only the fifth component and dependent score from bound N rows."""
    allowed = SINGLE_STOCKS if allowed_symbols is None else frozenset(allowed_symbols)
    if code not in allowed or len(source_rows) != len(score_rows) or len(source_rows) != len(n_rows):
        raise ValueError('HOLD_N_ROW_SET_CONFLICT')
    result=[]
    for source,score,n in zip(source_rows,score_rows,n_rows):
        structure=n.get('kb_n_structure')
        trend=n.get('kb_hold_trend_up')
        reason=n.get('kb_hold_trend_up_reason')
        if (str(source['trade_date']) != str(n.get('trade_date')) or n.get('ts_code') != code
                or trend not in (True,False,None) or isinstance(trend,int) and not isinstance(trend,bool)
                or not isinstance(structure,dict) or structure.get('rule_sha256') != rule_sha256
                or structure.get('helper_sha256') != helper_sha256
                or structure.get('state') != ('TREND_UP' if trend is True else reason)
                or trend is True and reason is not None or trend is not True and not isinstance(reason,str)):
            raise ValueError('HOLD_N_ROW_IDENTITY_CONFLICT:' + str(source['trade_date']))
        row=dict(score);row['kb_hold_trend_up']=trend;row['kb_hold_trend_up_reason']=reason
        values=[row.get(name) for name in COMPONENTS]
        if any(value not in (True,False,None) or isinstance(value,int) and not isinstance(value,bool) for value in values):
            raise ValueError('HOLD_COMPONENT_TRISTATE_INVALID:' + str(source['trade_date']))
        lower=sum(value is True for value in values);unknown=sum(value is None for value in values)
        row.update(kb_hold_score=lower if unknown==0 else None,kb_hold_score_min=lower,
                   kb_hold_score_max=lower+unknown,kb_hold_score_status='COMPLETE' if unknown==0 else 'PARTIAL_UNKNOWN')
        result.append(row)
    return result
