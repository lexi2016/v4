import pandas as pd

from ops.kb_anomaly_events import project_anomaly_events


def _history():
    dates = pd.bdate_range('2025-01-01', periods=145).strftime('%Y%m%d').astype(int)
    rows = [dict(trade_date=int(d), open=9.9, high=10.1, low=9.8, close=10.0,
                 volume=100., pct_chg=0., ma60=9.8, zge_yellow_line=10.1,
                 kb_yidong=False) for d in dates]
    # a -> p -> q -> r: staged shrinking is valid without a one-day half volume.
    rows[140].update(open=10., high=10.6, low=9.95, close=10.5, volume=300., pct_chg=5., kb_yidong=True)
    rows[141].update(open=10.5, high=11.1, low=10.4, close=11., volume=270., pct_chg=4.76, zge_yellow_line=10.5)
    rows[142].update(open=10.9, high=11., low=10.4, close=10.8, volume=200., pct_chg=-1.82, zge_yellow_line=10.6)
    # A new eligible anchor on r cannot hide the already completed older event.
    rows[143].update(open=11., high=11.4, low=10.7, close=11.3, volume=220., pct_chg=4.63,
                     zge_yellow_line=10.6, kb_yidong=True)
    rows[144].update(open=11.3, high=11.5, low=11.2, close=11.4, volume=230., pct_chg=.88, zge_yellow_line=10.6)
    return pd.DataFrame(rows)


def test_ordered_multianchor_events_retain_prior_completion_and_today_signal():
    frame = _history()
    result, ledger = project_anomaly_events(frame)
    assert pd.isna(result.loc[140, 'kb_yidong_pullback_date'])
    assert pd.isna(result.loc[141, 'kb_yidong_resume_date'])
    q = result.iloc[142]
    assert q.kb_yidong_anchor_date == frame.trade_date.iloc[140]
    assert q.kb_yidong_peak_date == frame.trade_date.iloc[141]
    assert q.kb_yidong_pullback_date == frame.trade_date.iloc[142]
    assert q.kb_yidong_pullback_vol_ratio == 200 / 285
    assert bool(q.kb_yidong_ground_volume)
    assert 200 > 270 / 2
    r = result.iloc[143]
    assert r.kb_yidong_anchor_date == frame.trade_date.iloc[140]
    assert r.kb_yidong_resume_date == frame.trade_date.iloc[143]
    assert bool(r.kb_yidong_volume_resumed) and bool(r.kb_yidong_breakout)
    at_r = [x for x in ledger if x['asof_date'] == frame.trade_date.iloc[143] and x['anchor_date']]
    assert len(at_r) == 1  # same-day native anchor is not in the prior-20 window
    old = next(x for x in at_r if x['anchor_date'] == frame.trade_date.iloc[140])
    assert old['today_volume_resumed'] is True and old['today_breakout'] is True
    next_day = next(x for x in ledger if x['asof_date'] == frame.trade_date.iloc[144]
                    and x['anchor_date'] == frame.trade_date.iloc[140])
    assert next_day['today_volume_resumed'] is True
    assert old['ma60_class'] == 'NEAR' and old['origin_class'] == 'BELOW'


def test_prefix_invariance_and_no_retroactive_future():
    frame = _history()
    full, ledger = project_anomaly_events(frame)
    for n in (141, 142, 143, 144):
        partial, partial_ledger = project_anomaly_events(frame.iloc[:n])
        left = full.iloc[n-1].astype(object).where(pd.notna(full.iloc[n-1]), None)
        right = partial.iloc[-1].astype(object).where(pd.notna(partial.iloc[-1]), None)
        pd.testing.assert_series_equal(left, right, check_names=False)
        assert [x for x in ledger if x['asof_date'] == frame.trade_date.iloc[n-1]] == [
            x for x in partial_ledger if x['asof_date'] == frame.trade_date.iloc[n-1]]


def test_extended_or_missing_origin_and_broken_anchor_remain_distinct():
    frame = _history()
    frame.loc[139, 'zge_yellow_line'] = 9.
    frame.loc[143, 'kb_yidong'] = False
    result, ledger = project_anomaly_events(frame)
    event = next(x for x in ledger if x['asof_date'] == frame.trade_date.iloc[141]
                 and x['anchor_date'] == frame.trade_date.iloc[140])
    assert event['origin_class'] == 'EXTENDED'
    assert pd.isna(result.loc[143, 'kb_yidong_anchor_date'])
    frame = _history()
    frame.loc[139, 'zge_yellow_line'] = float('nan')
    result, ledger = project_anomaly_events(frame)
    coverage = next(x for x in ledger if x['asof_date'] == frame.trade_date.iloc[143] and x['anchor_date'] is None)
    assert coverage['complete_20'] is False
    frame = _history()
    frame.loc[143, ['low', 'open', 'close', 'high']] = [9.9, 10.2, 10.1, 10.3]
    result, ledger = project_anomaly_events(frame)
    old = next(x for x in ledger if x['asof_date'] == frame.trade_date.iloc[143]
               and x['anchor_date'] == frame.trade_date.iloc[140])
    assert old['state'] == 'ANCHOR_LOW_BROKEN'
    assert old['today_volume_resumed'] is None


def test_prior_twenty_includes_minus_twenty_excludes_minus_twenty_one_and_today():
    frame = _history()
    tail_dates = pd.bdate_range(pd.Timestamp(str(frame.trade_date.iloc[-1])) + pd.Timedelta(days=1),
                                periods=25).strftime('%Y%m%d').astype(int)
    tail = pd.DataFrame([dict(trade_date=int(day), open=11.3, high=11.5, low=11.1, close=11.3,
                              volume=100., pct_chg=0., ma60=10., zge_yellow_line=10.6,
                              kb_yidong=False) for day in tail_dates])
    frame = pd.concat([frame, tail], ignore_index=True)
    frame.loc[160, 'kb_yidong'] = True
    _, ledger = project_anomaly_events(frame)
    at = lambda i: [e for e in ledger if e['asof_date'] == frame.trade_date.iloc[i] and e['anchor_date']]
    assert frame.trade_date.iloc[140] in {e['anchor_date'] for e in at(160)}
    assert frame.trade_date.iloc[140] not in {e['anchor_date'] for e in at(161)}
    assert frame.trade_date.iloc[160] not in {e['anchor_date'] for e in at(160)}
    assert frame.trade_date.iloc[160] in {e['anchor_date'] for e in at(161)}
    coverage = lambda i: next(e for e in ledger if e['asof_date'] == frame.trade_date.iloc[i] and e['anchor_date'] is None)
    assert coverage(19)['complete_20'] is False and coverage(19)['today_resumed'] is None
    assert coverage(20)['complete_20'] is True and coverage(20)['today_resumed'] is False
    frame['kb_yidong'] = frame['kb_yidong'].astype(object)
    frame.loc[140, 'kb_yidong'] = None
    _, ledger = project_anomaly_events(frame)
    assert coverage(160)['complete_20'] is False
    assert coverage(161)['complete_20'] is True
