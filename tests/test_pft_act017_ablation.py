import numpy as np
import pandas as pd
from ops import pft_act015_replay as base
from ops.pft_act017_ablation import run_arm, timing_risk, freeze_picks, baseline_parity
from ops.pft_act017_diagnostics import (router_decomposition, contribution_at, EndpointMarks,
                                        interval_specs, portfolio_attribution)


def case(day, code='000001.SZ', lane='B1', score=.8):
    return dict(episode_id=day+'|'+code+'|'+lane, D=day, canonical_security_id=code,
                lane=lane, model_year=int(day[:4]), held_outer=0, rank_score=score,
                hard_eligible=True, S_prob_gated=.5, B_probability=.5,
                prior_anchor_date='', prior_anchor_low=np.nan, rank_position=1)


def environment():
    sessions = pd.bdate_range('2022-12-30', periods=12).strftime('%Y%m%d').tolist()
    risk = {d: dict(strict_state='RISK_ON', strict_cap=1.) for d in sessions}
    bars = {'000001.SZ': {d: dict(open=10., high=11., low=9., close=10., vol=10.,
        tradeable_basic=1., zge_yellow_line=1., limit_up_approx=0., limit_down_approx=0.) for d in sessions}}
    return sessions, risk, bars


def test_original_strict_defaults_exact_and_protection():
    s, risk, bars = environment()
    bars['000001.SZ'][s[3]]['zge_yellow_line'] = 20.
    picks = {s[1]: [case(s[1])]}
    expected_n, expected_l = base.portfolio(picks, bars, s, risk, 'STRICT', 'ALL', 3, asof=s[8])
    for scenario in ['BASELINE_STRICT', 'TIMING_ONLY', 'ROUTING_ONLY', 'TIMING_ROUTING']:
        n, l = run_arm(picks, bars, s, risk, scenario, asof=s[8])
        n['scenario'], l['scenario'] = 'STRICT', 'STRICT'
        pd.testing.assert_frame_equal(n, expected_n, check_exact=True)
        pd.testing.assert_frame_equal(l, expected_l, check_exact=True)
        assert l.iloc[0].exit_reason == 'YELLOW'
        assert l.iloc[0].exit_at == 'OPEN'


def test_timing_mapping_prior_signal_date_and_no_mid_trim():
    s, _, bars = environment()
    f = pd.DataFrame({'D': s, 'graded_state': ['STRONG']*len(s), 'graded_cap': 1.})
    f.loc[1:3, 'graded_state'] = ['NEUTRAL', 'WEAK', 'UNKNOWN']
    f.loc[1:3, 'graded_cap'] = [.5, 0., 0.]
    r = timing_risk(f)
    assert r.loc[1:3, 'strict_state'].tolist() == ['RISK_ON', 'RISK_OFF', 'UNKNOWN']
    assert r.loc[1:3, 'strict_cap'].tolist() == [.5, 0., 0.]
    n, l = run_arm({s[1]: [case(s[1])], s[2]: [case(s[2])]}, bars, s,
                   r.set_index('D').to_dict('index'), 'TIMING_ONLY', asof=s[5])
    entry = n.loc[n.D.eq(s[2])].iloc[0]
    assert entry.opening_cap == .5 and entry.entries == 1
    assert np.isclose(entry.opening_budget, .5/3)
    assert n.trimmed_lots.eq(0).all()
    assert l.iloc[0].exit_reason == 'MACRO' and l.iloc[0].exit_date == s[3]
    assert l.iloc[1].entry_status == 'MACRO_RISK_OFF'


def test_top3_all_tiers_pick_pairs_and_mechanical_score_confound():
    s, _, _ = environment(); days = s[1:4]
    predictions = pd.DataFrame([case(d, f'00000{i}.SZ', lane, score) for d in days
                               for i, lane, score in [(1,'B1',.04),(2,'B2',.03),(3,'B3',.02),(4,'B1',.01)]])
    baseline = pd.DataFrame([r for v in base.select_signals(predictions, 'ALL', 3).values() for r in v])
    baseline['rank_position'] = baseline.groupby('D').cumcount()+1
    thresholds = pd.DataFrame([dict(year=2023, B1_q80=.01, B2_q80=.01)])
    risk = pd.DataFrame({'D':days, 'daily_K':[3,2,0]})
    picked, routed = freeze_picks(baseline, predictions, thresholds, risk)
    assert picked.groupby(['config_id','D']).size().eq(3).all()
    assert routed.groupby('D').size().eq(3).all()
    assert routed.groupby('D').first().lane.eq('B3').all()
    summary, audit = router_decomposition(predictions, thresholds, baseline, routed, days)
    b1 = summary.loc[summary.period.eq('ALL') & summary.lane.eq('B1')].iloc[0]
    assert b1.hard_pool == 6 and b1.pass_q80 == 6
    assert b1.pass_raw_RF_below_B3_min_025 == 6
    assert b1.BASELINE_RAW_top3 == 3 and b1.Q80_B3_PRODUCT_top3 == 3
    assert audit.loc[audit.router_mode.eq('Q80_RAW_ALL_LANES')].groupby('D').first().lane.eq('B1').all()


def test_exact_cumulative_contributions_carryover_stale_mark_and_exit():
    s, risk, bars = environment()
    bars['000001.SZ'][s[2]]['close'] = 11.
    bars['000001.SZ'][s[3]].update(close=99., vol=0.)
    bars['000001.SZ'][s[4]].update(close=12., high=13.)
    picked = pd.DataFrame([case(s[1])]).assign(config_id=0, scenario='BASELINE_STRICT')
    n, l = run_arm({s[1]: [case(s[1])]}, bars, s, risk, 'BASELINE_STRICT', asof=s[6])
    n['config_id'], l['config_id'] = 0, 0
    lot = l.iloc[0].to_dict(); marks = EndpointMarks(bars, s)
    assert contribution_at(lot, s[1], marks) == 0
    assert contribution_at(lot, s[2], marks) == contribution_at(lot, s[3], marks)
    assert contribution_at(lot, s[4], marks) == lot['realized_pnl']
    for row in n.to_dict('records'):
        assert np.isclose(contribution_at(lot, row['D'], marks), row['NAV']-1, atol=1e-10, rtol=0)
    risk_frame = pd.DataFrame({'D':s, 'graded_state':'STRONG', 'strict_cap':1.})
    outputs = portfolio_attribution(n, l, bars, s, picked, risk_frame)
    assert outputs['attribution_reconciliation.csv'].reconciliation_error.abs().max() < 1e-10
    # A year boundary retains previous-close NAV, and a lot can span it without resetting cost basis.
    renamed = n.copy(); renamed.loc[renamed.index >= 3, 'D'] = pd.bdate_range('2024-01-02', periods=len(n)-3).strftime('%Y%m%d')
    spec = [x for x in interval_specs(renamed) if x['period']=='2024' and x['interval']=='PERIOD'][0]
    assert spec['start_D'] == renamed.iloc[2].D and spec['start_NAV'] == renamed.iloc[2].NAV


def test_peak_ties_earliest_and_previous_close_baseline():
    nav = pd.DataFrame({'D':['20231229','20240102','20240103','20240104'], 'NAV':[1.2,1.2,.9,.9]})
    result = [s for s in interval_specs(nav) if s['period']=='2024' and s['interval']=='MAX_DRAWDOWN'][0]
    assert result['start_D'] == '20231229' and result['end_D'] == '20240103'
    assert np.isclose(result['MDD'], -.25)


def test_real_year_boundary_lot_delta_uses_carry_in_net_mark():
    dates = ['20231227','20231228','20231229','20240102','20240103','20240104']
    _, _, template = environment()
    row = next(iter(template['000001.SZ'].values()))
    bars = {'000001.SZ': {d: dict(row) for d in dates}}
    bars['000001.SZ']['20231229'].update(close=10.5)
    bars['000001.SZ']['20240102'].update(close=10.8)
    risk = {d: dict(strict_state='RISK_ON', strict_cap=1.) for d in dates}
    picked = pd.DataFrame([case('20231228')]).assign(config_id=0, scenario='BASELINE_STRICT')
    n, l = run_arm({'20231228':[case('20231228')]}, bars, dates, risk, 'BASELINE_STRICT', asof=dates[-1])
    n['config_id'], l['config_id'] = 0, 0
    rf = pd.DataFrame({'D':dates, 'graded_state':'STRONG', 'strict_cap':1.})
    output = portfolio_attribution(n, l, bars, dates, picked, rf)
    atoms = output['lot_contributions.csv']
    atom = atoms.loc[atoms.period.eq('2024') & atoms.interval.eq('PERIOD')].iloc[0]
    prior_nav = n.loc[n.D.eq('20231229'), 'NAV'].iloc[0]
    assert atom.start_D == '20231229' and atom.contribution_start != 0
    assert np.isclose(atom.contribution_delta, n.NAV.iloc[-1]-prior_nav, atol=1e-10, rtol=0)
    assert np.isclose(atom.contribution_end, l.realized_pnl.iloc[0])
