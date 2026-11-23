import numpy as np
import pandas as pd
import pytest
from ops import pft_act019_b3_cap as p
from ops import pft_act015_replay as base
from ops.pft_act016_inputs import hybrid_picks
from ops.pft_act017_ablation import as_picks


def row(code, lane, score, *, s=.9, b=.9, day='20230103'):
    raw = s*b if lane == 'B3' else score
    threshold = np.nan if lane == 'B3' else .2
    return dict(episode_id=day+'|'+code+'|'+lane,D=day,canonical_security_id=code,lane=lane,
        rank_score=score,act015_rank_score=score,S_prob_gated=s,B_probability=b,
        model_year=int(day[:4]),held_outer=0,hard_eligible=True,raw_score=raw,hybrid_score=raw,q80_threshold=threshold,
        pass_raw_q80=lane=='B3' or score>=threshold,percentile_score=.5,
        prior_anchor_date='',prior_anchor_low=np.nan)


def thresholds():
    return pd.DataFrame([dict(year=2023,B1_q80=.2,B2_q80=.2)])


def test_raw_order_quota_scans_beyond_top3_and_original_parity():
    f = pd.DataFrame([row('600001.SH','B3',-99,s=.99,b=.99),
                      row('600002.SH','B3',99,s=.98,b=.99),
                      row('600003.SH','B3',99,s=.97,b=.99),
                      row('000004.SZ','B1',.7),row('000005.SZ','B2',.6)])
    new,original,audit = p.cap_picks(f,thresholds())
    assert new.canonical_security_id.tolist() == ['600001.SH','000004.SZ','000005.SZ']
    assert new.original_order_rank.tolist() == [1,4,5]
    assert new.rank_position.tolist() == [1,2,3]
    assert audit.quota_skipped.tolist() == [False,True,True,False,False]
    expected = hybrid_picks(f,thresholds(),pd.DataFrame({'D':['20230103'],'daily_K':[3]}))
    expected['config_id'] = 1
    p.verify_original(original,expected)
    expected.loc[expected.index[0],'rank_score'] = 7.
    with pytest.raises(AssertionError):
        p.verify_original(original,expected)


def test_dedup_before_cap_never_reroutes_rejected_b3_into_b1():
    f = pd.DataFrame([row('600001.SH','B3',.1,s=1,b=1),
                      row('600002.SH','B3',.1,s=.99,b=.99),
                      row('600002.SH','B1',.8),
                      row('000003.SZ','B1',.7),row('000004.SZ','B2',.6)])
    new,original,audit = p.cap_picks(f,thresholds())
    assert new.canonical_security_id.tolist() == ['600001.SH','000003.SZ','000004.SZ']
    assert audit.loc[audit.canonical_security_id.eq('600002.SH'),'lane'].tolist() == ['B3']
    assert new.duplicated(p.c.IDENTITY).sum() == 0


def test_code_then_lane_ties_q80_inclusive_and_fewer_than_three():
    f = pd.DataFrame([row('000003.SZ','B2',.2),row('000003.SZ','B1',.2),
                      row('000004.SZ','B3',.1,s=.5,b=.5),
                      row('000002.SZ','B1',.1999)])
    new,original,audit = p.cap_picks(f,thresholds())
    assert new.canonical_security_id.tolist() == ['000004.SZ','000003.SZ']
    assert new.lane.tolist() == ['B3','B1']
    assert new.rank_position.tolist() == [1,2]
    assert not audit.quota_skipped.any()
    assert len(original) == 2


def test_quota_resets_each_day_and_raw_scores_unchanged():
    f = pd.DataFrame([row('600001.SH','B3',-.9,day=d) for d in ['20230103','20230104']])
    new,_,_ = p.cap_picks(f,thresholds())
    assert new.groupby('D').size().tolist() == [1,1]
    np.testing.assert_array_equal(new.rank_score,[-.9,-.9])
    for column in ['q80_threshold','raw_score','act015_rank_score','pass_raw_q80']:
        altered = f.copy()
        altered.loc[0,column] = False if column == 'pass_raw_q80' else 99.
        with pytest.raises(AssertionError):
            p.cap_picks(altered,thresholds())
    altered = f.copy(); altered.loc[0,'hard_eligible'] = False
    with pytest.raises(ValueError,match='HARD_ENVELOPE'):
        p.cap_picks(altered,thresholds())


def test_new_arm_retains_original_engine_failed_entry_and_risk_off():
    sessions=pd.bdate_range('2022-12-30',periods=10).strftime('%Y%m%d').tolist()
    day=sessions[1]
    candidates=pd.DataFrame([row('600001.SH','B3',.5,s=1,b=1,day=day),
        row('600002.SH','B3',.5,s=.99,b=.99,day=day),
        row('000003.SZ','B1',.8,day=day),row('000004.SZ','B2',.7,day=day),
        row('000005.SZ','B2',.6,day=day)])
    selected,_,_=p.cap_picks(candidates,thresholds())
    bars={code:{d:dict(open=10.,high=11.,low=9.,close=10.,vol=10.,tradeable_basic=1.,
        zge_yellow_line=1.,limit_up_approx=0.,limit_down_approx=0.) for d in sessions}
        for code in candidates.canonical_security_id}
    bars['000003.SZ'][sessions[2]]['vol']=0.
    risk={d:dict(strict_state='RISK_ON',strict_cap=1.) for d in sessions}
    n,l=base.portfolio(as_picks(selected),bars,sessions,risk,'STRICT','ALL',3,asof=sessions[8])
    assert l.status.tolist()==['CLOSED','FAILED_ENTRY','CLOSED']
    assert set(l.canonical_security_id)==set(selected.canonical_security_id)
    assert '000005.SZ' not in set(l.canonical_security_id)
    np.testing.assert_allclose(l.loc[l.status.eq('CLOSED'),'allocation'],[1/9,1/9])
    risk[day]=dict(strict_state='RISK_OFF',strict_cap=0.)
    _,off=base.portfolio(as_picks(selected),bars,sessions,risk,'STRICT','ALL',3,asof=sessions[8])
    assert not off.status.isin(['OPEN','CLOSED']).any()


def test_fill_counts_use_entry_year_positive_allocation_and_filled_status():
    picked=pd.DataFrame([dict(config_id=3,D='20231229',lane='B3'),
                         dict(config_id=3,D='20240102',lane='B1')])
    ledger=pd.DataFrame([dict(config_id=3,D='20231229',entry_date='20240102',lane='B3',status='CLOSED',allocation=.1),
        dict(config_id=3,D='20240102',entry_date='20240103',lane='B1',status='OPEN',allocation=.1),
        dict(config_id=3,D='20240102',entry_date='20240103',lane='B3',status='OPEN',allocation=0.),
        dict(config_id=3,D='20240102',entry_date='20240103',lane='B3',status='FAILED_ENTRY',allocation=.1)])
    counts=p.selection_fill_counts(picked,ledger).set_index(['config_id','period'])
    assert counts.loc[(3,'2023'),['selected','B3_selected','filled','B3_actual_filled']].tolist()==[1,1,0,0]
    assert counts.loc[(3,'2024'),['selected','B3_selected','filled','B3_actual_filled']].tolist()==[1,0,2,1]
    assert counts.loc[(3,'FULL'),['selected','filled','B3_actual_filled']].tolist()==[2,2,1]


def test_hotspots_explicit_four_arm_trace_and_risk_off_interpretation():
    day,code=p.a18.CASES[0]
    picked=pd.DataFrame([{**row(code,'B3',.5,day=day), 'config_id':i,'scenario':scenario,
                         'rank_position':1} for i,scenario in p.CONFIGS])
    ledger=pd.DataFrame([dict(config_id=i,D=day,episode_id=day+'|'+code+'|B3',
        canonical_security_id=code,lane='B3',status='FAILED_ENTRY',entry_status='MACRO_RISK_OFF',
        entry_date='20231108',exit_date='',exit_reason='',allocation=0.,buy_fee=0.,sell_fee=0.,
        realized_pnl=np.nan) for i,_ in p.CONFIGS])
    audit=pd.DataFrame([row(code,'B3',.5,day=day)])
    risk=pd.DataFrame([dict(D=day,strict_state='RISK_OFF')])
    cases,traces=p.hotspot_comparisons(picked,ledger,audit,risk)
    assert len(cases)==24
    actual=cases.loc[cases.case_D.eq(day)]
    assert actual.config_id.tolist()==[0,1,2,3]
    assert actual.selected.all() and not actual.filled.any()
    assert actual.interpretation.eq('original STRICT RISK_OFF; no saved-loss claim').all()
    assert traces.config_id.tolist()==[0,1,2,3]
    assert traces.entry_status.eq('MACRO_RISK_OFF').all()
