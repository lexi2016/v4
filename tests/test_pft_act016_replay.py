import math
import numpy as np
import pandas as pd
from ops import pft_act015_replay as base
from ops.pft_act016_inputs import annual_thresholds, hybrid_picks
from ops.pft_act016_replay import run_portfolio, baseline_parity


def case(d, code='000001.SZ', lane='B1', score=1.):
    return dict(episode_id=d+'|'+code+'|'+lane, canonical_security_id=code, D=d, lane=lane,
                model_year=int(d[:4]), held_outer=0, rank_score=score, hard_eligible=True,
                S_prob_gated=.8, B_probability=.8, prior_anchor_date='', prior_anchor_low=np.nan)


def environment(n=15, codes=('000001.SZ',)):
    sessions = pd.bdate_range('2022-12-30', periods=n).strftime('%Y%m%d').tolist()
    risk = {d: dict(strict_state='RISK_ON', strict_cap=1., graded_state='STRONG', graded_cap=1.) for d in sessions}
    bars = {c: {d: dict(open=10., high=11., low=10., close=10., vol=100., tradeable_basic=1.,
                       zge_yellow_line=1., limit_up_approx=0., limit_down_approx=0.) for d in sessions} for c in codes}
    return sessions, risk, bars


def calibration():
    dates = ['20220103', '20220104', '20220105', '20230103', '20230104', '20230105',
             '20240103', '20250103', '20260105']
    values = [0., .3, .6, .2, .4, .6, .4, .4, .4]
    market = pd.DataFrame({'D': dates, **{k: values for k in ['cw_share','cy_share','wy_share']}})
    starter = pd.DataFrame([case('20220103', str(i)+'.SZ', lane, score) for lane in ['B1','B2'] for i, score in enumerate([0., 1., 2., 3., 4.])])
    predictions = pd.DataFrame([case(d, lane=lane, score=10.) for d in dates[3:] for lane in ['B1', 'B2']])
    return market, predictions, starter


def test_exact_tertiles_boundaries_q80_and_future_immunity():
    market, predictions, starter = calibration()
    t, risk = annual_thresholds(market, predictions, starter)
    assert t.iloc[0].B1_q80 == 3.2
    assert t.iloc[0].q33 == np.quantile([0.,.3,.6], 1/3)
    assert t.iloc[0].q67 == np.quantile([0.,.3,.6], 2/3)
    # Exact q33 equality is neutral; exact q67 equality strong.
    market.loc[3:5, ['cw_share','cy_share','wy_share']] = [[t.iloc[0].q33]*3, [t.iloc[0].q67]*3, [0.]*3]
    _, risk2 = annual_thresholds(market, predictions, starter)
    assert risk2.loc[3:5, 'graded_state'].tolist() == ['NEUTRAL', 'STRONG', 'WEAK']
    changed = predictions.copy(); changed.loc[changed.D.ge('20240101'), 'rank_score'] = -999
    market2 = market.copy(); market2.loc[market2.D.ge('20240101'), ['cw_share','cy_share','wy_share']] = .99
    t2, r2 = annual_thresholds(market2, changed, starter)
    pd.testing.assert_frame_equal(t.iloc[:1], t2.iloc[:1])
    pd.testing.assert_frame_equal(risk2.loc[risk2.D.lt('20240101')], r2.loc[r2.D.lt('20240101')])
    market[['cw_share','cy_share','wy_share']] = .5
    _, degenerate = annual_thresholds(market, predictions, starter)
    assert degenerate.loc[degenerate.D.ge('20230101'), 'graded_state'].eq('STRONG').all()


def test_hybrid_q80_raw_b1_score_b3_product_crosslane_dedup_and_liquidity_backfill():
    t = pd.DataFrame([dict(year=2023, B1_q80=.8, B2_q80=.8)])
    day = '20230103'
    rows = [case(day, '000001.SZ', 'B1', .799), case(day, '000002.SZ', 'B2', .8),
            case(day, '000003.SZ', 'B3', 99), case(day, '000004.SZ', 'B1', .9),
            case(day, '000004.SZ', 'B3', 99), case(day, '000005.SZ', 'B1', .9)]
    f = pd.DataFrame(rows)
    risk = pd.DataFrame([dict(D=day, daily_K=3)])
    picks = hybrid_picks(f, t, risk)
    assert picks.canonical_security_id.tolist() == ['000004.SZ','000005.SZ','000002.SZ']
    assert picks.iloc[0].lane == 'B1' and picks.iloc[0].hybrid_score == .9
    amount = pd.DataFrame({'D': [day]*5, 'canonical_security_id': [f'00000{i}.SZ' for i in range(1,6)],
                           'amount_cny': [1e8, np.nan, 1e8, 1e8-1, 1e8+1]})
    filtered = hybrid_picks(f, t, risk, amount)
    assert filtered.canonical_security_id.tolist() == ['000005.SZ','000003.SZ']
    assert math.isclose(filtered.iloc[1].hybrid_score, .64)
    assert filtered.iloc[1].rank_score == 99
    f.loc[f.canonical_security_id.eq('000004.SZ'), 'lane'] = 'B1'
    assert hybrid_picks(f, t, risk).canonical_security_id.tolist() == ['000004.SZ','000005.SZ','000002.SZ']


def test_no_inherited_exit_or_tier_trim_and_neutral_new_sleeve():
    s, risk, bars = environment()
    picks = {d: [case(d)] for d in s[1:5]}
    # Existing exposure > .5, but neutral still opens its own .5/H sleeve.
    risk[s[4]].update(graded_state='NEUTRAL', graded_cap=.5)
    bars['000001.SZ'][s[2]].update(zge_yellow_line=100., close=9., low=8.)
    n, l = run_portfolio(picks, bars, s, risk, 'EXPANDING_HYBRID', 5, asof=s[5])
    assert n.iloc[-1].entries == 1 and n.iloc[-1].opening_budget > 0
    assert n.trimmed_lots.sum() == 0 and l.status.eq('OPEN').all()
    risk[s[4]].update(graded_state='WEAK', graded_cap=0.)
    n, l = run_portfolio(picks, bars, s, risk, 'EXPANDING_HYBRID', 5, asof=s[5])
    assert n.iloc[-1].entries == 0 and n.exits.sum() == 0
    assert l.status.eq('OPEN').sum() == 3


def test_fixed_touch_entry_day_next_open_gap_down_lock_and_cash():
    s, risk, bars = environment()
    d, entry, blocked, sell = s[1:5]
    bars['000001.SZ'][entry].update(low=9.5, close=10.)
    bars['000001.SZ'][blocked].update(open=8., close=8., high=8., low=8., limit_down_approx=1.)
    bars['000001.SZ'][sell].update(open=7., low=7., high=9.)
    n, l = run_portfolio({d:[case(d)]}, bars, s, risk, 'EXPANDING_HYBRID_SL5', 5, .05, asof=sell)
    lot = l.iloc[0]
    assert lot.trigger_date == entry and lot.exit_date == sell and lot.exit_price == 7.
    assert lot.fixed_stop_trigger_low == 9.5 and lot.fixed_stop_threshold == 9.5
    assert lot.exit_reason == 'FIXED_STOP' and lot.open_exit_failed_attempts == 1
    expected = .8 + .2*7*(1-base.SELL_FEE)/(10*(1+base.BUY_FEE))
    assert math.isclose(n.iloc[-1].NAV, expected)
    assert (n.opening_budget <= n.opening_cash_before_sales+1e-12).all()


def test_scheduled_close_precedes_new_touch_and_earlier_touch_has_open_priority():
    s, risk, bars = environment()
    d = s[1]; target = s[4]
    bars['000001.SZ'][target].update(low=9., close=9.4)
    _, l = run_portfolio({d:[case(d)]}, bars, s, risk, 'EXPANDING_HYBRID_SL5', 3, .05, asof=s[5])
    assert l.iloc[0].exit_reason == 'SCHEDULED' and l.iloc[0].exit_at == 'CLOSE'
    bars['000001.SZ'][s[3]].update(low=9.5)
    _, l = run_portfolio({d:[case(d)]}, bars, s, risk, 'EXPANDING_HYBRID_SL5', 3, .05, asof=s[5])
    assert l.iloc[0].exit_reason == 'FIXED_STOP' and l.iloc[0].exit_at == 'OPEN'


def test_invalid_stop_price_and_unfilled_slot_no_replacement():
    s, risk, bars = environment(codes=('000001.SZ','000002.SZ'))
    bars['000001.SZ'][s[2]].update(low=1., vol=0.)
    bars['000001.SZ'][s[3]].update(low=np.nan)
    bars['000002.SZ'][s[2]].update(open=10., close=10., high=10., low=10., limit_up_approx=1.)
    n, l = run_portfolio({s[1]:[case(s[1]),case(s[1], '000002.SZ')]}, bars, s, risk, 'EXPANDING_HYBRID_SL5', 5, .05, asof=s[3])
    assert l.status.eq('FAILED_ENTRY').all()  # untradeable + locked; no rerank/replacement
    assert n.NAV.eq(1.).all()
    bars['000001.SZ'][s[2]].update(vol=100., low=10.)
    _, l = run_portfolio({s[1]:[case(s[1])]}, bars, s, risk, 'EXPANDING_HYBRID_SL5', 5, .05, asof=s[3])
    assert l.iloc[0].trigger_date == '' and l.iloc[0].status == 'OPEN'


def test_baseline_default_exact_identity_and_parity_guard(tmp_path):
    s, risk, bars = environment()
    picks = {s[1]: [case(s[1])]}
    expected, old_l = base.portfolio(picks, bars, s, risk, 'STRICT', 'ALL', 3, asof=s[8])
    actual, new_l = run_portfolio(picks, bars, s, risk, 'BASELINE_STRICT', 3, asof=s[8])
    actual['scenario'], new_l['scenario'] = 'STRICT', 'STRICT'
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    pd.testing.assert_frame_equal(old_l, new_l, check_exact=True)
    expected['config_id'] = 0
    expected.to_parquet(tmp_path/'daily_nav.parquet', index=False)
    actual['scenario'] = 'BASELINE_STRICT'
    assert baseline_parity(actual, tmp_path)['status'] == 'PASS_EXACT'


def test_manifest_rejects_canary_issuer_drift_and_wrong_weights(tmp_path, monkeypatch):
    from ops import pft_act016_inputs as inputs
    import pytest
    source = {'identity': {'generation_id': 'generation'}, 'backtest': {'panel_sha256': 'panel'}}
    m = {'source': source, 'sessions': ['20220103'],
         'outputs_sha256': {'models/2023_held0/S_MAIN.joblib': 'main'}}
    rank = dict(source=source, fit_manifest_sha256='sealed', pre_replay_seal_sha256='sealed',
                market_manifest_sha256='sealed', execution_market_read=False, sessions=m['sessions'])
    replay = dict(rank, rank_manifest_sha256='sealed')
    sm = dict(batch='ACT-016', fit_calls=0, mode='FULL', calibration_model_year=2023,
              issuer_held_excluded_from_all_scoring_weights=True, chronological_2022_oos=False,
              date_scope=['20220101','20221231'], fit_manifest_sha256='sealed', source=source,
              fit_models_sha256=m['outputs_sha256'], sha256='starter', rows=1,
              date_min='20220103', date_max='20220103')
    monkeypatch.setattr(inputs, 'verified_predictions', lambda _: (m, pd.DataFrame()))
    monkeypatch.setattr(inputs.c, 'read_manifest', lambda _, name: rank if name == 'rank_manifest.json' else replay)
    monkeypatch.setattr(inputs.c.old, '_sha_file', lambda _: 'sealed')
    monkeypatch.setattr(inputs.c, 'calendar', lambda *_: (pd.DataFrame(), m['sessions'], {'crosswalk_sha256':'x'}, {}))
    monkeypatch.setattr(inputs.c, 'verified_file', lambda path, _: path)
    monkeypatch.setattr(inputs.c.old, '_read_json', lambda _: sm)
    starter = tmp_path/'starter.parquet'
    pd.DataFrame([case('20220103')]).to_parquet(starter, index=False)
    args = (tmp_path, tmp_path, tmp_path, tmp_path, starter, tmp_path/'manifest.json')
    assert len(inputs.validate_seals(*args)[-1]) == 1
    for field, value in [('mode','CANARY'), ('issuer_held_excluded_from_all_scoring_weights',False),
                         ('calibration_model_year',2024), ('chronological_2022_oos',True),
                         ('date_scope',['20220101','20230101']), ('fit_models_sha256',{'bad':'hash'})]:
        saved = sm[field]; sm[field] = value
        with pytest.raises(ValueError, match='STARTER_'):
            inputs.validate_seals(*args)
        sm[field] = saved
