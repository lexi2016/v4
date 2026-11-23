import numpy as np
import pandas as pd
import pytest
from ops.pft_act010_replay import BUY_FEE,SELL_FEE,fill_status,standalone,picks_by_day,portfolio,excluded_episode_ids

SESSIONS=['20260105','20260106','20260107','20260108','20260109','20260112','20260113']


def bar(price=10.,**updates):
    return dict(open=price,high=price*1.01,low=price*.99,close=price,vol=100.,tradeable_basic=1,
                limit_up_approx=0,limit_down_approx=0,**updates)


def case(code='000001.SZ',day='20260105',lane='B1',prob=.9,episode='x'):
    return dict(episode_id=episode,canonical_security_id=code,D=day,lane=lane,raw_trigger=True,
                eligible=True,BASELINE_B_prob=prob,FULL_B_prob=prob,S_prob_gated=.9)


def test_fees_calendar_holiday_and_cost_contained_mdd():
    bars={d:bar() for d in SESSIONS}
    result=standalone(case(),bars,SESSIONS,5,SESSIONS[-1])
    assert result['terminal_date']=='20260112'
    expected=(1-SELL_FEE)/(1+BUY_FEE)-1
    assert result['net_return_pct']==pytest.approx(expected*100)
    assert result['running_close_mdd_pct']==pytest.approx(expected*100)
    assert result['fees_per_share']==pytest.approx(.02)


def test_locked_entry_missing_unknown_and_strict_exit_do_not_find_later_bar():
    bars={d:bar() for d in SESSIONS}
    bars['20260106'].update(high=10.,low=10.,limit_up_approx=1)
    assert standalone(case(),bars,SESSIONS,3)['status']=='NO_ENTRY'
    bars['20260106']['limit_up_approx']=np.nan
    assert fill_status(bars['20260106'],'BUY')=='ONE_PRICE_LIMIT_UNKNOWN'
    bars['20260106']=bar();del bars['20260108']
    result=standalone(case(),bars,SESSIONS,3)
    assert result['status']=='PLANNED_EXIT_UNAVAILABLE' and result['stale_marks']==1


def test_missing_intermediate_mark_is_carried_and_last_day_is_censored():
    bars={d:bar() for d in SESSIONS};del bars['20260107']
    result=standalone(case(),bars,SESSIONS,3)
    assert result['status']=='VALID' and result['stale_marks']==1
    assert standalone(case(day=SESSIONS[-1]),bars,SESSIONS,3,SESSIONS[-1])['entry_status']=='ENTRY_AFTER_ASOF'


def test_top_k_has_no_fill_information_and_pooled_tie_is_code_then_lane():
    frame=pd.DataFrame([case('000002.SZ',prob=.8,episode='a'),case('000001.SZ',prob=.8,episode='b'),
                        case('000001.SZ',lane='B2',prob=.9,episode='c')])
    picks=picks_by_day(frame,'FULL_B','ALL',1)['20260105']
    assert len(picks)==1 and picks[0]['episode_id']=='c'
    picks=picks_by_day(frame,'ORIGINAL','ALL',1)['20260105']
    assert picks[0]['canonical_security_id']=='000001.SZ' and picks[0]['lane']=='B1'
    frame.loc[:,'S_prob_gated']=np.nan
    assert not picks_by_day(frame,'FULL_B_S030','ALL',3)


def test_failed_top_pick_is_not_replaced_and_failed_budget_stays_cash():
    frame=pd.DataFrame([case('000001.SZ',prob=.9,episode='a'),case('000002.SZ',prob=.8,episode='b')])
    bars={'000001.SZ':{},'000002.SZ':{d:bar() for d in SESSIONS}}
    nav,lots,summary=portfolio(frame,bars,SESSIONS,'FULL_B','ALL',1,3)
    assert summary['selected']==1 and summary['executed']==0 and summary['failed']==1
    assert all(n['NAV']==1. and n['cash']==1. for n in nav)
    assert summary['no_position_fraction']==1.
    assert lots[0]['entry_status']=='MISSING_SCHEDULED_BAR'


def test_cash_uses_previous_nav_no_later_exit_funding_and_fees():
    frame=pd.DataFrame([case(day=d,episode=d) for d in SESSIONS[:5]])
    bars={'000001.SZ':{d:bar() for d in SESSIONS}}
    nav,lots,summary=portfolio(frame,bars,SESSIONS,'FULL_B','B1',3,3)
    assert nav[0]['NAV']==1 and nav[0]['no_position']==1
    for i,n in enumerate(nav):
        assert n['cash']>=-1e-12
        if i and n['entries']:assert n['opening_budget']<=nav[i-1]['NAV']/3+1e-12
    first=lots[0]
    assert first['quantity']==pytest.approx((1/3)/(10*(1+BUY_FEE)))
    assert summary['buy_fees']>0 and summary['sell_fees']>0 and summary['MDD_pct']<0
    assert summary['executed']==5


def test_delay_sell_lock_keeps_residual_then_exits_later():
    frame=pd.DataFrame([case()]);bars={'000001.SZ':{d:bar() for d in SESSIONS}}
    bars['000001.SZ']['20260108'].update(high=10.,low=10.,limit_down_approx=1)
    nav,lots,summary=portfolio(frame,bars,SESSIONS,'ORIGINAL','B1',3,3)
    assert lots[0]['exit_date']=='20260109' and lots[0]['delayed_exit_days']==1
    assert summary['closed']==1 and summary['open']==0
    assert nav[3]['open_lots']==1


def test_final_d_selected_and_open_lots_retained():
    frame=pd.DataFrame([case(day=SESSIONS[-2],episode='open'),case(day=SESSIONS[-1],episode='pending')])
    bars={'000001.SZ':{d:bar() for d in SESSIONS}}
    nav,lots,summary=portfolio(frame,bars,SESSIONS,'ORIGINAL','B1',3,20)
    assert summary['selected']==2 and summary['open']==1 and summary['entry_after_asof']==1
    assert summary['residual_exit_fee_reserve']>0
    assert nav[-1]['positions_value_after_exit_cost']>0


def test_pooled_hard_gate_alternate_lane_is_not_a_removed_stock_day():
    a=case(lane='B1',prob=.9,episode='a');a['S_prob_gated']=.1
    b=case(lane='B2',prob=.8,episode='b');b['S_prob_gated']=.8
    frame=pd.DataFrame([a,b])
    assert excluded_episode_ids(frame,'ALL','FULL_B_S030')==set()
    assert excluded_episode_ids(frame,'B1','FULL_B_S030')=={'a'}
