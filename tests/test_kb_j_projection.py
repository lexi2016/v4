import math

import pandas as pd
import pytest

from ops import kb_signal_authority as owner


def rows_with_zero_volume():
    rows = []
    for i in range(12):
        close = -3.0 + i * .2
        rows.append({'ts_code':'301468.SZ', 'trade_date':20260101+i, 'open':close,
                     'high':close+.3, 'low':close-.3, 'close':close,
                     'vol':0.0 if i in (9, 10) else 100.0,
                     'pre_close':close-.2, 'pct_chg':1.0})
    return rows


def test_j_uses_pinned_hlc_prefix_while_b1_volume_gate_stays_closed():
    rows = rows_with_zero_volume()
    for row in rows:
        for key in ('open','high','low','close','pre_close'):
            row[key] += 10
    projected = owner.project_bound_kb_j('301468.SZ', rows)
    frame = owner.append_kb_signals(pd.DataFrame(rows))
    assert projected[:8] == [{'trade_date':r['trade_date'],'kb_b1_j':None} for r in rows[:8]]
    for i in range(8, len(rows)):
        prefix = [owner.DailyData(r['ts_code'], str(r['trade_date']), r['open'], r['high'], r['low'],
                                  r['close'], r['vol'], 0.0, r['pct_chg'], r['pre_close']) for r in rows[:i+1]]
        assert projected[i]['kb_b1_j'] == owner._source_kdj(prefix)[2]
        assert frame.iloc[i]['kb_b1_j'] == projected[i]['kb_b1_j']
    assert pd.isna(frame.iloc[-1]['kb_b1'])
    assert pd.isna(frame.iloc[-1]['kb_b1_score'])
    assert not pd.isna(frame.iloc[8]['kb_b1'])


def test_j_accepts_finite_negative_qfq_hlc_without_opening_b1_gate():
    rows = rows_with_zero_volume()
    projected = owner.project_bound_kb_j('301468.SZ', rows)
    frame = owner.append_kb_signals(pd.DataFrame(rows))
    assert projected[-1]['kb_b1_j'] == frame.iloc[-1]['kb_b1_j']
    assert projected[-1]['kb_b1_j'] is not None
    assert pd.isna(frame.iloc[-1]['kb_b1'])


def test_invalid_hlc_prefix_stays_unknown_and_dates_are_strict():
    rows = rows_with_zero_volume()
    rows[4]['low'] = math.nan
    result = owner.project_bound_kb_j('301468.SZ', rows)
    assert all(item['kb_b1_j'] is None for item in result)
    rows[4]['low'] = rows[4]['close'] - .3
    rows[-1]['trade_date'] = rows[-2]['trade_date']
    with pytest.raises(ValueError, match='KB_TRADE_DATES_NOT_UNIQUE_SORTED'):
        owner.project_bound_kb_j('301468.SZ', rows)
