import math
import numpy as np
import pandas as pd
import pytest
from ops import pft_act015_replay as base
from ops.pft_act020_replay import select_ready,run_portfolio,validate_audit,baseline_parity
from ops.pft_act020_timing import level_and_brakes,crowd_percentiles,timing_daily


def case(day,code='000001.SZ',lane='B1',score=1.):
    return dict(episode_id=day+'|'+code+'|'+lane,canonical_security_id=code,D=day,lane=lane,
        model_year=int(day[:4]),held_outer=0,rank_score=score,hard_eligible=True,
        S_prob_gated=.8,B_probability=.8,pass_raw_q80=True,percentile_score=.8,
        prior_anchor_date='',prior_anchor_low=np.nan)


def environment():
    s=pd.bdate_range('2022-12-30',periods=15).strftime('%Y%m%d').tolist()
    risk={d:dict(strict_state='RISK_ON',strict_cap=1.) for d in s}
    bars={'000001.SZ':{d:dict(open=10.,high=11.,low=10.,close=10.,vol=100.,tradeable_basic=1.,
        zge_yellow_line=1.,limit_up_approx=0.,limit_down_approx=0.) for d in s}}
    return s,risk,bars


def test_exact_quantile_boundaries_and_one_tier_brake_saturation():
    args=dict(slope=0.,liquidity=1.,crowd=.8,q33=.3,q67=.6,q20=-.1,q25=.9)
    assert level_and_brakes(.3,**args)[:2] == (1,1)
    assert level_and_brakes(.6,**args)[:2] == (2,2)
    assert level_and_brakes(.6,-.1,.9,.8,.3,.6,-.1,.9) == (2,2,False,False,False)
    assert level_and_brakes(.6,-.11,.89,.81,.3,.6,-.1,.9) == (2,1,True,True,True)
    assert level_and_brakes(.2,-.11,.89,.81,.3,.6,-.1,.9)[:2] == (0,0)
    assert level_and_brakes(.6,0.,.1,1.,.3,.6,-.1,.9)[1] == 2
    assert level_and_brakes(np.nan,**args)[1] == -1


def test_crowd_inclusive_ties_first9_fallback_and_40_window():
    counts=np.array([4]*9+[4,3]+list(range(40)))
    p=crowd_percentiles(counts)
    assert (p[:9] == .5).all() and p[9] == 1.
    assert p[10] == 1/11
    assert p[-1] == 1.
    assert p[40] == np.mean(counts[1:41] <= counts[40])
    with pytest.raises(ValueError):
        crowd_percentiles([np.nan])


def test_timing_prior_year_only_future_mutation():
    days=pd.bdate_range('2022-01-03','2026-11-20').strftime('%Y%m%d')
    m=pd.DataFrame(dict(D=days,amount_MA5=1.,amount_MA20=1.,liquidity_trend=1.))
    signal=np.sin(np.arange(len(m))/9)*.2+.5
    for k in ['cw_share','cy_share','wy_share']:
        m[k]=signal
    counts=pd.Series(np.arange(sum(days >= '20230101'))%13,index=days[days >= '20230101'])
    f,t=timing_daily(m,counts)
    changed=m.copy()
    changed.loc[changed.D.ge('20260101'),['cw_share','cy_share','wy_share']]=.99
    altered,ta=timing_daily(changed,counts)
    pd.testing.assert_frame_equal(t,ta)
    pd.testing.assert_frame_equal(f.loc[f.D.lt('20260101')],altered.loc[altered.D.lt('20260101')])
    prior=f.loc[f.D.lt('20230101')]
    assert t.iloc[0].q33 == np.quantile(prior.B_comp,1/3)
    assert t.iloc[0].slope_q20 == np.quantile(prior.B_slope_5d.dropna(),.2)
    assert f.loc[f.D.ge('20230101')].strict_state.ne('UNKNOWN').all()
    with pytest.raises(ValueError,match='ALL_940'):
        timing_daily(m,counts.iloc[:-1])


def test_adv_before_dedup_topk_inclusive_threshold_and_date_scope():
    d='20230103'
    a=pd.DataFrame([case(d,'000001.SZ','B1',9),case(d,'000001.SZ','B3',8),
        *[case(d,f'00000{i}.SZ',score=8-i) for i in range(2,6)]])
    validate_audit(a)
    adv=pd.DataFrame(dict(canonical_security_id=[f'00000{i}.SZ' for i in range(1,6)],D=d,
        adv20_cny=[np.nan,1e8-1,1e8,3e8,5e8]))
    selected=select_ready(a,'RF',1e8,adv,pd.Series({d:2}))
    assert selected.canonical_security_id.tolist() == ['000003.SZ','000004.SZ']
    assert select_ready(a,'RF').canonical_security_id.tolist() == ['000001.SZ','000002.SZ','000003.SZ']
    a.loc[0,'pass_raw_q80']=False
    assert select_ready(a,'PERCENTILE').iloc[0].lane == 'B3'
    assert select_ready(a,'RF',daily_k=pd.Series({d:0})).empty
    a.loc[0,'D']='20270101'
    with pytest.raises(ValueError,match='ENVELOPE'):
        validate_audit(a)


def test_fixed_stop_entry_touch_next_directional_open_and_cash():
    s,risk,bars=environment()
    d,entry,blocked,sell=s[1:5]
    bars['000001.SZ'][entry].update(low=9.5)
    bars['000001.SZ'][blocked].update(open=8.,close=8.,high=8.,low=8.,limit_down_approx=1.)
    bars['000001.SZ'][sell].update(open=7.,low=7.,high=9.)
    n,l=run_portfolio({d:[case(d)]},bars,s,risk,'V2_RF_SL5','ALL',5,asof=sell)
    lot=l.iloc[0]
    assert lot.trigger_date == entry and lot.exit_date == sell and lot.exit_at == 'OPEN'
    assert lot.exit_price == 7. and lot.exit_reason == 'FIXED_STOP' and lot.open_exit_failed_attempts == 1
    assert lot.fixed_stop_threshold == 9.5 and lot.fixed_stop_trigger_low == 9.5
    assert math.isclose(n.iloc[-1].NAV,.8+.2*7*(1-base.SELL_FEE)/(10*(1+base.BUY_FEE)))


def test_original_protection_priority_scheduled_precedence_and_macro_weak():
    s,risk,bars=environment();d,entry=s[1:3]
    bars['000001.SZ'][entry].update(low=9.,zge_yellow_line=11.)
    _,l=run_portfolio({d:[case(d)]},bars,s,risk,'V2_RF_SL5','ALL',5,asof=s[4])
    assert l.iloc[0].exit_reason == 'YELLOW' and l.iloc[0].trigger_date == entry
    bars['000001.SZ'][entry].update(low=10.,zge_yellow_line=1.)
    bars['000001.SZ'][s[4]].update(low=9.)
    _,l=run_portfolio({d:[case(d)]},bars,s,risk,'V2_RF_SL5','ALL',3,asof=s[5])
    assert l.iloc[0].exit_reason == 'SCHEDULED' and l.iloc[0].exit_at == 'CLOSE'
    risk[entry].update(strict_state='RISK_OFF',strict_cap=0.)
    _,l=run_portfolio({d:[case(d)]},bars,s,risk,'V2_RF','ALL',5,asof=s[4])
    assert l.iloc[0].trigger_date == entry and l.iloc[0].exit_reason == 'MACRO'


def test_no_neutral_trim_preserves_original_budget_and_baseline_exact(tmp_path):
    s,risk,bars=environment()
    picks={d:[case(d)] for d in s[1:5]}
    risk[s[4]].update(strict_cap=.5)
    n,l=run_portfolio(picks,bars,s,risk,'V2_RF','ALL',5,asof=s[6])
    assert n.trimmed_lots.sum() == 0
    assert (n.opening_budget <= n.opening_cash_before_sales+1e-12).all()
    originals=[];ledgers=[];actuals=[];actledgers=[]
    for h in (3,5):
        expected,old=base.portfolio(picks,bars,s,risk,'STRICT','ALL',h,asof=s[8])
        actual,new=run_portfolio(picks,bars,s,risk,'BASELINE_STRICT','ALL',h,asof=s[8])
        originals.append(expected);ledgers.append(old);actuals.append(actual);actledgers.append(new)
    pd.concat(originals).to_parquet(tmp_path/'daily_nav.parquet',index=False)
    pd.concat(ledgers).to_parquet(tmp_path/'portfolio_ledger.parquet',index=False)
    parity=baseline_parity(pd.concat(actuals),pd.concat(actledgers),tmp_path)
    assert parity['portfolio_ledger.parquet']['status'] == 'PASS_EXACT'
