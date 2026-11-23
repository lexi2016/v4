import numpy as np
import pandas as pd
import pytest
from ops import pft_act010_replay as old
from ops import pft_act013_replay as new

DAYS=[d.strftime('%Y%m%d') for d in pd.bdate_range('20260105',periods=16)]


def bar(price=10.,**kw):
    r=dict(open=price,close=price,high=price*1.01,low=price*.99,vol=100.,tradeable_basic=1,
           limit_up_approx=0,limit_down_approx=0,zge_yellow_line=8.)
    r.update(kw);return r


def case(day=DAYS[0],episode='x',code='000001.SZ',lane='B1',**kw):
    r=dict(episode_id=episode,canonical_security_id=code,D=day,lane=lane,raw_trigger=True,eligible=True,
           BASELINE_B_prob=.9,FULL_B_prob=.9,S_prob_gated=.9,prior_anchor_date='20251201',S_c_vs_recent_anchor_low_pct=25.)
    r.update(kw);return r


def test_none_exact_kernel_parity_all_rails_and_horizons():
    cases=[case(d,d+lane,code=code,lane=lane) for d in DAYS[:8]
           for code,lane in [('000001.SZ','B1'),('000002.SZ','B2'),('000003.SZ','B3')]]
    f=pd.DataFrame(cases)
    bars={c:{d:bar(10+i*.1) for i,d in enumerate(DAYS)} for c in f.canonical_security_id.unique()}
    bars['000001.SZ'][DAYS[1]]=bar(high=10.,low=10.,limit_up_approx=1)
    bars['000002.SZ'].pop(DAYS[6])
    for rail in old.RAILS:
        for h in [5,10]:
            n,l,s=new.portfolio(f,bars,DAYS,rail,h,'NONE',{},asof=DAYS[-1])
            refn,refl,refs=old.portfolio(f,bars,DAYS,old.POLICIES[-1],rail,3,h)
            pd.testing.assert_frame_equal(pd.DataFrame(n)[pd.DataFrame(refn).columns],pd.DataFrame(refn),check_exact=True)
            for k,v in refs.items():
                assert s[k]==v or (pd.isna(s[k]) and pd.isna(v))
    for h in [5,10]:
        a=new.event(cases[0],bars['000001.SZ'],DAYS,h,'NONE',{},DAYS[-1])
        assert {k:a[k] for k in old.standalone(cases[0],bars['000001.SZ'],DAYS,h,DAYS[-1])}==old.standalone(cases[0],bars['000001.SZ'],DAYS,h,DAYS[-1])


def test_close_break_next_open_gap_and_anchor_fixed_not_future():
    b={d:bar() for d in DAYS};b[DAYS[2]]=bar(9.,zge_yellow_line=9.5)
    b[DAYS[3]]=bar(7.,close=12.,high=12.1,low=6.9,zge_yellow_line=1.)
    c=case();r=new.event(c,b,DAYS,5,'RISK',{},DAYS[-1])
    assert r['exit_date']==DAYS[3] and r['exit_at']=='OPEN' and r['terminal_close']==7.
    assert r['trigger_date']==DAYS[2] and r['exit_reason']=='YELLOW'
    assert r['running_close_mdd_pct']<-30
    b[DAYS[2]]=bar(7.9,zge_yellow_line=1.)
    r=new.event(c,b,DAYS,5,'RISK',{},DAYS[-1])
    assert r['exit_reason']=='ANCHOR' # D close=10, fixed 25pct above anchor=8.
    b[DAYS[0]]['close']=np.nan
    b[DAYS[3]]=bar()
    r=new.event(c,b,DAYS,5,'RISK',{},DAYS[-1])
    assert r['exit_reason']=='BASELINE' and r['missing_anchor_days']>0


def test_halt_one_price_retry_and_scheduled_fallback_reason():
    b={d:bar() for d in DAYS};b[DAYS[1]]=bar(zge_yellow_line=11.)
    b[DAYS[2]]=bar(vol=0.,tradeable_basic=0)
    b[DAYS[3]]=bar(8.,high=8.,low=8.,limit_down_approx=1)
    b[DAYS[4]]=bar(7.)
    r=new.event(case(),b,DAYS,5,'RISK',{},DAYS[-1])
    assert r['trigger_date']==DAYS[1] and r['exit_date']==DAYS[4]
    assert r['open_exit_failed_attempts']==2 and r['exit_reason']=='YELLOW'
    # Missing/invalid open on due day may still allow the prescheduled close.
    b[DAYS[4]]=bar(vol=0.,tradeable_basic=0);b[DAYS[5]]=bar(open=np.nan)
    r=new.event(case(),b,DAYS,5,'RISK',{},DAYS[-1])
    assert r['exit_at']=='CLOSE' and r['exit_reason']=='BASELINE' and r['trigger_reasons']=='YELLOW'


def test_trail_never_before_eight_percent_and_uses_held_close_peak():
    b={d:bar() for d in DAYS};c=case(S_c_vs_recent_anchor_low_pct=np.nan)
    b[DAYS[1]]=bar(10.,close=10.7,high=10.8);b[DAYS[2]]=bar(10.0)
    r=new.event(c,b,DAYS,5,'RISK',{},DAYS[-1])
    assert r['exit_reason']=='BASELINE'
    b[DAYS[1]]=bar(10.,close=10.8,high=10.9);b[DAYS[2]]=bar(10.26);b[DAYS[3]]=bar(9.)
    r=new.event(c,b,DAYS,5,'RISK',{},DAYS[-1])
    assert r['trigger_date']==DAYS[2] and r['exit_date']==DAYS[3] and r['exit_reason']=='TRAIL'


def test_macro_unknown_blocks_entry_off_queues_protective_sale():
    b={d:bar() for d in DAYS};c=case()
    assert new.event(c,b,DAYS,5,'MACRO',{},DAYS[-1])['entry_status']=='MACRO_UNKNOWN'
    g={DAYS[0]:'RISK_ON',DAYS[1]:'UNKNOWN',DAYS[2]:'RISK_OFF'}
    r=new.event(c,b,DAYS,5,'MACRO',g,DAYS[-1])
    assert r['trigger_date']==DAYS[2] and r['exit_date']==DAYS[3] and r['exit_reason']=='MACRO'
    censored=new.event(c,b,DAYS,10,'RISK',{},DAYS[3])
    assert censored['status']=='RIGHT_CENSORED' and censored['exit_status']=='RIGHT_CENSORED'


def test_topk_frozen_no_replacement_and_no_same_open_cash_round_trip():
    f=pd.DataFrame([case(d,d) for d in DAYS[:10]])
    b={'000001.SZ':{d:bar() for d in DAYS}}
    # Only first signal has permission to enter. Others remain frozen blocked slots.
    gate={d:'RISK_ON' for d in DAYS};gate[DAYS[3]]='RISK_OFF'
    n,l,s=new.portfolio(f,b,DAYS,'ALL',5,'MACRO',gate,asof=DAYS[-1])
    prev_cash=1.
    for i,row in enumerate(n):
        if row['entries']+row['failed_entries']:
            prevnav=n[i-1]['NAV'] if i else 1.
            assert row['opening_budget']==min(prevnav/5,max(prev_cash,0.))
        prev_cash=row['cash']
    closed=[x for x in l if x['status']=='CLOSED' and x['exit_reason']=='MACRO']
    assert closed and all(x['exit_date']==DAYS[4] for x in closed)
    assert s['blocked_macro_entries']==1 and all(x['cash']>=-1e-10 for x in n)
    # Pooled top3 is chosen before the gate and before missing fills.
    frame=pd.DataFrame([case(code=f'{i:06d}.SZ',episode=str(i),FULL_B_prob=1-i*.01) for i in range(1,5)])
    n,l,s=new.portfolio(frame,{},DAYS,'ALL',5,'RISK',{},asof=DAYS[-1])
    assert s['selected']==3 and len(l)==3 and s['failed']==3


def test_none_event_active_position_days_are_counted_without_risk_operands():
    b={d:bar() for d in DAYS}
    r=new.event(case(),b,DAYS,5,'NONE',{},DAYS[-1])
    assert r['active_position_days']==5 and r['missing_yellow_days']==0
    r=new.event(case(),b,DAYS,10,'NONE',{},DAYS[3])
    assert r['active_position_days']==3 and r['status']=='RIGHT_CENSORED'


def test_monthly_nav_return_and_drawdown_include_prior_month_end():
    f=pd.DataFrame([dict(scenario='NONE',rail='ALL',horizon=5,date=d,NAV=v,no_position=0)
                    for d,v in [('20260130',1.2),('20260202',1.08),('20260203',1.14)]])
    r=new.monthly_nav(f).iloc[-1]
    assert r.start_NAV==1.2 and r.net_return_pct==pytest.approx(-5.) and r.MDD_pct==pytest.approx(-10.)
