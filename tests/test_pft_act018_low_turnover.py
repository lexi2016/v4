from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ops import pft_act018_low_turnover as s


def book_fixture(n=35, count=3):
    dates = pd.bdate_range('2024-11-01', periods=n).strftime('%Y%m%d').tolist()
    raw = pd.DataFrame([dict(ts_code=f'{i+1:06d}.SZ', trade_date=d, open=10., high=12., low=8.,
                             close=10., vol=100., pre_close=10., pct_chg=0., tradeable_basic=1.)
                        for i in range(count) for d in dates])
    book = s.base.PriceBook.from_frame(raw)
    book.values['zge_white_line'] = np.full(book.valid.shape, 9.)
    return book


def arm(top=1, horizon=10, clock='open', dynamic=False):
    return s.Arm('test', 'hard', top, horizon, clock, dynamic=dynamic)


def test_signed_arms_all_enumerated_with_no_duplicate_names():
    plan = s.arms()
    assert len(plan) == len({a.name for a in plan}) == 58
    e1 = [a for a in plan if a.experiment == 'E1']
    assert len(e1) == 48
    assert {a.horizon for a in e1} == {10, 15}
    assert {a.top for a in e1} == {3, 5, 20}
    assert len([a for a in plan if a.experiment == 'E2']) == 6
    assert len([a for a in plan if a.experiment == 'E3']) == 4


def test_capacity_no_single_name_overlap_and_no_blocked_backfill():
    book = book_fixture()
    signals = {d: [0, 1, 2] for d in range(30)}
    book.values['open'][1, 0] = 10.6  # rank 1 blocked, rank 3 must not fill
    daily, stats = s.simulate(book, signals, arm(top=2), 0.)
    assert daily.fills.iloc[1] == 1
    assert daily.holding_count.iloc[1] == 1
    assert daily.holding_count.max() == 2
    assert stats['max_holding'] == 2
    assert stats['blocked']['capacity_or_occupied'] > 0
    np.testing.assert_allclose(daily.cash+daily.invested, daily.nav)
    assert daily.cash.min() >= -1e-12


def test_fixed_market_session_target_fees_and_paired_zero_closed_form():
    book = book_fixture()
    net, stats = s.simulate(book, {0:[0]}, arm(), .0015)
    zero, zstats = s.simulate(book, {0:[0]}, arm(), 0.)
    assert net.fills.iloc[1] == net.sales.iloc[10] == 1
    assert stats['buys'] == stats['sales'] == zstats['sales'] == 1
    assert stats['avg_realized_hold_sessions'] == 10
    assert stats['avg_realized_elapsed_sessions'] == 9
    assert net.nav.iloc[-1] == pytest.approx((1-.0015)/(1+.0015))
    assert zero.nav.iloc[-1] == 1.
    assert stats['buy_fees']+stats['sell_fees'] == pytest.approx(1-net.nav.iloc[-1])
    assert net.buy_notional.sum() == pytest.approx(1/1.0015)
    assert net.sell_notional.sum() == pytest.approx(1/1.0015)


def test_dynamic_close_stop_next_open_t_plus_one_and_no_same_close_fill():
    book = book_fixture()
    book.values['close'][1,0] = 8.9  # buy at open10, close signal
    book.values['open'][2,0] = 9.8
    daily, stats = s.simulate(book, {0:[0]}, arm(dynamic=True, horizon=20), 0.)
    assert daily.sales.iloc[1] == 0
    assert daily.holding_count.iloc[1] == 1
    assert daily.sales.iloc[2] == 1
    assert daily.nav.iloc[-1] == pytest.approx(.98)
    assert stats['avg_realized_hold_sessions'] == 2
    assert stats['exit_reasons'] == {'white':1}


def test_dynamic_trailing_peak_and_blocked_next_open_retry_ignores_future_ohlcv():
    book = book_fixture()
    book.values['zge_white_line'][:] = 1.
    book.values['close'][1,0] = 11.
    book.values['close'][2,0] = 10.  # >8% below observed 11 peak
    book.values['open'][3,0] = 9.5  # lower-cap proxy blocks
    book.values['open'][4,0] = 9.8
    book.values['vol'][4,0] = np.nan
    book.values['high'][4,0] = np.nan
    book.valid[4,0] = False
    daily, stats = s.simulate(book, {0:[0]}, arm(dynamic=True, horizon=20), 0.)
    assert daily.sales.iloc[2] == daily.sales.iloc[3] == 0
    assert daily.sales.iloc[4] == 1
    assert stats['delayed_exit_attempts'] == 1
    assert stats['exit_reasons'] == {'trailing8':1}
    assert daily.nav.iloc[-1] == pytest.approx(.98)


def test_dynamic_twentieth_market_session_cap_and_blocked_close_retry():
    book = book_fixture()
    book.valid[20,0] = False  # buy day1 -> twentieth inclusive20
    daily, stats = s.simulate(book, {0:[0]}, arm(dynamic=True, horizon=20), 0.)
    assert daily.sales.iloc[19] == daily.sales.iloc[20] == 0
    assert daily.sales.iloc[21] == 1
    assert stats['avg_realized_hold_sessions'] == 21
    assert stats['exit_reasons'] == {'cap20':1}


def test_no_forced_beyond_asof_and_late_signals_residual():
    book = book_fixture(n=12)
    daily, stats = s.simulate(book, {10:[0]}, arm(), .0015)
    assert stats['buys'] == 1 and stats['sales'] == 0
    assert stats['residual_positions'] == 1
    assert stats['avg_realized_hold_sessions'] is None
    assert daily.holding_count.iloc[-1] == 1


def test_causal_ranking_stable_codes_f5_b_and_top_before_execution():
    rows = pd.DataFrame(dict(trade_date=['20241101']*4, session=[0]*4,
        code_index=[3,2,1,0],ts_code=['000004.SZ','000003.SZ','000002.SZ','000001.SZ'],
        s_rule_score=[.9,.9,.9,.8],f5_s1_pass=[True,True,False,True],b_any=[False,True,True,True]))
    assert s.prior.ranked_signals(rows,'s_rule_score',2) == {0:[1,2]}
    assert s.prior.ranked_signals(rows,'s_rule_score',2,True,True) == {0:[2,0]}


def test_exact_t10_target_path_threshold_benchmark_and_maturity():
    book = book_fixture(n=25, count=3)
    book.values['close'][10:,0] = 11.5
    candidates = pd.DataFrame(dict(session=[0,0,0,20],code_index=[0,1,2,0]))
    result, ledger = s.attach_targets(candidates, book)
    assert result[s.TARGET].iloc[:3].tolist() == [1.,0.,0.]
    assert np.isnan(result[s.TARGET].iloc[3])
    assert result[s.TARGET+'_date'].iloc[0] == book.dates[10]
    assert ledger['known'] == 3 and ledger['positive'] == 1
    book.values['close'][3,0] = 9.  # < -8% complete path -> negative despite good endpoint
    result, _ = s.attach_targets(candidates, book)
    assert result[s.TARGET].iloc[0] == 0.
    book.valid[4,0] = False
    result, _ = s.attach_targets(candidates, book)
    assert np.isnan(result[s.TARGET].iloc[0])


def test_quarter_train_only_group_purge_and_strict_exact_maturity():
    rows = pd.DataFrame(dict(trade_date=['20240701','20240910','20240911','20241101'],
        ts_code=['000001.SZ']*4,_anchor_date=['shared','','','shared'],
        rebuild_episode_id=['']*4,exec_t10_target=[1.,0.,1.,0.],
        exec_t10_target_date=['20240715','20241001','20240930','20241115']))
    train, predict, report = s.prior.quarter_masks(rows,'2024Q4',s.TARGET)
    assert train.tolist() == [False,False,True,False]
    assert predict.tolist() == [False,False,False,True]
    assert report['latest_train_target'] == '20240930'
    assert report['purged_rows'] == 1


class MockClassifier:
    calls = 0
    def fit(self,x,y,sample_weight):
        type(self).calls += 1
        assert sample_weight[y==0].sum() == pytest.approx(sample_weight[y==1].sum())
        return self
    def predict_proba(self,x):
        return np.tile([.4,.6], (len(x),1))


def test_nine_actual_mock_fits_weight_reload_and_no_refit_resume(tmp_path):
    rows=[]
    for year in (2023,2024,2025,2026):
        for q in (1,2,3,4):
            quarter=f'{year}Q{q}'
            if quarter<'2023Q4':
                continue
            day='20241101' if quarter=='2024Q4' else s.base.quarter_start(quarter)
            target=pd.bdate_range(day,periods=11)[-1].strftime('%Y%m%d')
            for i in (0,1):
                rows.append({**{f:float(i) for f in s.FEATURES},'trade_date':day,
                    'ts_code':f'{i+1:06d}.SZ','_anchor_date':'','rebuild_episode_id':'',
                    s.TARGET:float(i),s.TARGET+'_date':target})
    candidates=pd.DataFrame(rows)
    MockClassifier.calls=0
    scored, ledger=s.fit_models(candidates,{'test':'binding'},tmp_path,estimator_factory=MockClassifier)
    assert MockClassifier.calls == ledger['actual_fits'] == 9
    assert len(ledger['quarters']) == 9
    assert all(r['reload_prediction_check']=='PASS' and len(r['model_sha256'])==64 for r in ledger['quarters'])
    again, replay=s.fit_models(candidates,{'test':'binding'},tmp_path,resume=True,estimator_factory=MockClassifier)
    assert MockClassifier.calls == 9 and replay['actual_fits'] == 0 and replay['reused'] == 9
    pd.testing.assert_series_equal(scored.t10_score,again.t10_score)
    with pytest.raises(s.Act018Error,match='MISMATCH'):
        s.fit_models(candidates,{'test':'other'},tmp_path,resume=True,estimator_factory=MockClassifier)


def test_metrics_actual_two_sided_turnover_pair_fee_drag_and_segment_counts():
    book=book_fixture()
    frames=[]
    for mode,fee in [('NET',.0015),('ZERO',0.)]:
        daily,_=s.simulate(book,{0:[0]},arm(),fee)
        daily=daily.assign(strategy='one',horizon=10,mode=mode,regime='sideways')
        daily['daily_return']=daily.nav.pct_change().fillna(daily.nav.iloc[0]-1)
        daily['benchmark_daily_return']=0.
        frames.append(daily)
    metrics=s.segment_metrics(pd.concat(frames,ignore_index=True))
    row=metrics.loc[(metrics['mode']=='NET') & (metrics.segment_kind=='full')].iloc[0]
    assert row.actual_buys == row.actual_sales == 1
    assert row.avg_realized_hold_sessions == 10
    assert row.paired_fee_drag_pp == pytest.approx((1-(1-.0015)/(1+.0015))*100)
    assert row.annualized_actual_turnover_two_sided == pytest.approx(frames[0].turnover.sum()*252/35)
