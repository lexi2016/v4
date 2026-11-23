import math
import numpy as np
import pandas as pd
from ops.pft_act015_replay import regimes, select_signals, portfolio, protection, metrics, CompactHistory, BAR_FIELDS
from ops.pft_act010_replay import BUY_FEE, SELL_FEE


def case(d, code='000001.SZ', lane='B1', score=1.):
    return {'episode_id': d+'|'+code+'|'+lane, 'canonical_security_id': code, 'D': d,
            'lane': lane, 'model_year': int(d[:4]), 'held_outer': 0, 'rank_score': score,
            'hard_eligible': True, 'prior_anchor_date': '', 'prior_anchor_low': np.nan}


def environment(n=15, start='2022-12-30', codes=('000001.SZ',)):
    sessions = pd.bdate_range(start, periods=n).strftime('%Y%m%d').tolist()
    risk = {d: {'strict_state': 'RISK_ON', 'strict_cap': 1., 'graded_state': 'STRONG', 'graded_cap': 1.} for d in sessions}
    def row():
        return dict(open=10., high=11., low=9., close=10., vol=100., tradeable_basic=1.,
                    zge_yellow_line=1., limit_up_approx=0., limit_down_approx=0.)
    bars = {c: {d: row() for d in sessions} for c in codes}
    return sessions, risk, bars


def test_prior126_rolling_survives_year_boundary_and_weak_equality():
    dates = pd.bdate_range('2022-06-01', periods=180).strftime('%Y%m%d')
    f = pd.DataFrame({'D': dates, 'cw_share': .6, 'cy_share': .6, 'wy_share': .6})
    g = regimes(f)
    assert g.graded_state.iloc[:126].eq('UNKNOWN').all()
    assert g.graded_state.iloc[126:].eq('WEAK').all()
    assert g.graded_cap.iloc[126:].eq(0).all()
    changed = f.copy(); changed.loc[170:, ['cw_share', 'cy_share', 'wy_share']] = .9
    pd.testing.assert_frame_equal(regimes(changed).iloc[:170], g.iloc[:170])
    pd.testing.assert_frame_equal(regimes(f.iloc[:150]), g.iloc[:150].reset_index(drop=True))


def test_ranking_uses_eligible_best_lane_stable_ties_and_never_weak_truth():
    rows = [case('20230103', '000002.SZ', 'B2', 4), case('20230103', lane='B3', score=3),
            case('20230103', lane='B1', score=3), case('20230103', '000003.SZ', score=2)]
    f = pd.DataFrame(rows); f['label'] = np.nan
    picks = select_signals(f, 'ALL')['20230103']
    assert [(r['canonical_security_id'], r['lane']) for r in picks] == [('000002.SZ', 'B2'), ('000001.SZ', 'B1'), ('000003.SZ', 'B1')]
    f.loc[0, 'hard_eligible'] = False
    assert all(r['lane'] != 'B2' for r in select_signals(f, 'ALL')['20230103'])
    assert all(r['lane'] != 'B2' for r in select_signals(pd.DataFrame(rows), 'B1_B3')['20230103'])


def test_hard6_gap_is_next_open_and_strict_original_has_no_extra_stop():
    sessions, risk, bars = environment()
    d, entry, following = sessions[1:4]
    bars['000001.SZ'][entry].update(close=9.3, low=9.)
    bars['000001.SZ'][following].update(open=8., low=7.5, high=10.)
    picks = {d: [case(d)]}
    _, matched = portfolio(picks, bars, sessions, risk, 'STRICT_MATCHED', 'ALL', 5, asof=sessions[5])
    lot = matched.iloc[0]
    assert lot.trigger_date == entry and lot.exit_date == following and lot.exit_at == 'OPEN'
    assert lot.exit_reason == 'HARD_6PCT' and lot.net_return_pct < -20
    _, strict = portfolio(picks, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=sessions[5])
    assert strict.iloc[0].status == 'OPEN'


def test_yellow_and_locked_anchor_trailing_trigger_from_held_close_only():
    sessions, risk, bars = environment()
    d, entry, peak, fall, sell = sessions[1:6]
    bars['000001.SZ'][peak].update(close=11., high=11.5)
    bars['000001.SZ'][fall].update(close=10.4)
    _, ledger = portfolio({d: [case(d)]}, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=sell)
    lot = ledger.iloc[0]
    assert lot.trigger_date == fall and lot.exit_date == sell and lot.exit_reason == 'TRAIL'
    c = case(d); c.update(prior_anchor_date=sessions[0], prior_anchor_low=10.1)
    _, anchored = portfolio({d: [c]}, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=peak)
    assert anchored.iloc[0].trigger_date == entry and anchored.iloc[0].exit_reason == 'ANCHOR'


def test_directional_open_stop_lock_retries_then_scheduled_close_may_fill():
    sessions, risk, bars = environment()
    d, entry, blocked, retry = sessions[1:5]
    bars['000001.SZ'][entry]['zge_yellow_line'] = 11.
    bars['000001.SZ'][blocked].update(open=9., close=9., high=9., low=9., limit_down_approx=1.)
    _, l = portfolio({d: [case(d)]}, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=retry)
    assert l.iloc[0].open_exit_failed_attempts == 1 and l.iloc[0].exit_date == retry
    assert l.iloc[0].exit_at == 'OPEN'


def test_graded_oldest_whole_lot_trim_and_unknown_no_forced_unwind():
    sessions, risk, bars = environment()
    picks = {d: [case(d)] for d in sessions[1:4]}
    # At open sessions[5], prior close sessions[4] limits existing exposure.
    risk[sessions[4]].update(graded_state='MID', graded_cap=.5)
    nav, ledger = portfolio(picks, bars, sessions, risk, 'GRADED', 'ALL', 5, asof=sessions[5])
    trimmed = ledger.loc[ledger.exit_reason.eq('GRADED_TRIM')]
    assert len(trimmed) == 1 and trimmed.iloc[0].D == sessions[1]
    assert nav.iloc[-1].opening_exposure_after_sales <= nav.iloc[-2].NAV*.5
    risk[sessions[4]].update(graded_state='UNKNOWN', graded_cap=0.)
    _, unknown = portfolio(picks, bars, sessions, risk, 'GRADED', 'ALL', 5, asof=sessions[5])
    assert unknown.status.eq('OPEN').all()


def test_failed_oldest_trim_is_explicit_and_next_tradable_whole_lot_used():
    codes = ('000001.SZ', '000002.SZ', '000003.SZ')
    sessions, risk, bars = environment(codes=codes)
    picks = {d: [case(d, c)] for d, c in zip(sessions[1:4], codes)}
    risk[sessions[4]].update(graded_state='MID', graded_cap=.5)
    bars[codes[0]][sessions[5]].update(open=10., high=10., low=10., close=10., limit_down_approx=1.)
    nav, ledger = portfolio(picks, bars, sessions, risk, 'GRADED', 'ALL', 5, asof=sessions[5])
    assert nav.iloc[-1].constrained_trim_attempts == 1
    trimmed = ledger.loc[ledger.exit_reason.eq('GRADED_TRIM')]
    assert len(trimmed) == 1 and trimmed.iloc[0].canonical_security_id == codes[1]
    assert ledger.loc[ledger.canonical_security_id.eq(codes[0]), 'status'].iloc[0] == 'OPEN'


def test_open_sale_cash_never_advanced_and_failed_slots_not_redistributed():
    sessions, risk, bars = environment(codes=('000001.SZ', '000002.SZ'))
    picks = {d: [case(d)] for d in sessions[1:5]}
    bars['000001.SZ'][sessions[4]]['zge_yellow_line'] = 11.
    nav, ledger = portfolio(picks, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=sessions[6])
    assert (nav.opening_budget <= nav.opening_cash_before_sales+1e-12).all()
    assert nav.loc[nav.D.eq(sessions[5]), 'exits'].iloc[0] > 0
    # Two selected slots, one lock: half of the fixed opening budget stays cash.
    picks = {sessions[1]: [case(sessions[1]), case(sessions[1], '000002.SZ')]}
    bars['000002.SZ'][sessions[2]].update(open=10., high=10., low=10., close=10., limit_up_approx=1.)
    nav, ledger = portfolio(picks, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=sessions[2])
    assert ledger.status.eq('OPEN').sum() == 1 and ledger.entry_status.eq('ONE_PRICE_UP_LOCK').sum() == 1
    assert math.isclose(ledger.loc[ledger.status.eq('OPEN'), 'allocation'].iloc[0], .1)
    assert math.isclose(nav.iloc[-1].cash, .9)


def test_year_boundary_position_continuity_realized_exit_year_and_annual_mdd():
    sessions, risk, bars = environment(12, '2023-12-27')
    d = sessions[0]
    nav, ledger = portfolio({d: [case(d)]}, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=sessions[8])
    assert ledger.iloc[0].exit_date.startswith('2024') and ledger.iloc[0].D.startswith('2023')
    summary = metrics(nav, ledger)
    y23 = summary.loc[summary.period.eq('2023')].iloc[0]
    y24 = summary.loc[summary.period.eq('2024')].iloc[0]
    full = summary.loc[summary.period.eq('FULL')].iloc[0]
    assert y23.closed_count == 0 and y24.closed_count == 1
    assert math.isclose(y24.start_NAV, y23.final_NAV)
    assert math.isclose(full.annual_mean_closed_count, .25)
    assert full.payoff_ratio != full.payoff_ratio  # no winner => unknown payoff
    expected = 1-.2+.2*(1-SELL_FEE)/(1+BUY_FEE)
    assert math.isclose(nav.iloc[-1].NAV, expected)


def test_scheduled_exit_delay_and_right_censored_open_residual():
    sessions, risk, bars = environment()
    d, entry = sessions[1:3]
    target = sessions[4]
    bars['000001.SZ'][target].update(vol=0., tradeable_basic=0.)
    _, ledger = portfolio({d: [case(d)]}, bars, sessions, risk, 'STRICT', 'ALL', 3, asof=sessions[5])
    assert ledger.iloc[0].exit_date == sessions[5] and ledger.iloc[0].delayed_exit_days == 1
    assert ledger.iloc[0].exit_reason == 'DELAYED_SCHEDULED'
    _, residual = portfolio({d: [case(d)]}, bars, sessions, risk, 'STRICT', 'ALL', 5, asof=sessions[3])
    assert residual.iloc[0].status == 'OPEN' and residual.iloc[0].residual_value_after_exit_cost > 0


def test_compact_marks_and_empty_selection_metrics_are_valid():
    sessions, risk, bars = environment()
    f = pd.DataFrame([{'trade_date': d, **r} for d, r in bars['000001.SZ'].items()])
    compact = CompactHistory(f)
    assert compact.get(sessions[2]) == bars['000001.SZ'][sessions[2]]
    assert compact.get('20990101') is None
    nav, ledger = portfolio({}, {}, sessions, risk, 'GRADED', 'ALL', 3, asof=sessions[5])
    assert nav.NAV.eq(1).all() and ledger.empty
    out = metrics(nav, ledger)
    assert out.closed_count.eq(0).all() and out.no_position_fraction.eq(1).all()
