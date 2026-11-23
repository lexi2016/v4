import numpy as np
import pandas as pd
import pytest
from ops import pft_act015_replay as base
from ops import pft_act018_percentile as p
from ops.pft_act016_inputs import hybrid_picks
from ops.pft_act017_ablation import as_picks


def case(day, code='000001.SZ', lane='B1', score=.8, s=.8, b=.8):
    return dict(episode_id=day+'|'+code+'|'+lane, D=day, canonical_security_id=code,
                lane=lane, model_year=int(day[:4]), held_outer=0, rank_score=score,
                hard_eligible=True, S_prob_gated=s, B_probability=b,
                prior_anchor_date='', prior_anchor_low=np.nan)


def seeds():
    ab = pd.DataFrame([case('20220103', f'00000{i}.SZ', lane, float(i))
                       for lane in ['B1','B2'] for i in range(5)])
    b3 = pd.DataFrame([case('20220103', f'60000{i}.SH', 'B3', 1., .5+.1*i, .8) for i in range(5)])
    return ab, b3


def test_exact_midrank_ties_extremes_and_invalid_inputs():
    np.testing.assert_array_equal(p.midrank_percentile([1,1,3,4], [0,1,2,3,4,5]), [0,.25,.5,.625,.875,1])
    np.testing.assert_array_equal(p.midrank_percentile([2,2,2], [1,2,3]), [0,.5,1])
    for scores, values in [([], [1]), ([2,1], [1]), ([np.nan], [1]), ([1], [np.nan])]:
        with pytest.raises(ValueError):
            p.midrank_percentile(scores, values)


def test_prior_year_calibration_future_immune_and_lane_hard_isolation():
    ab,b3 = seeds()
    predictions = pd.DataFrame([case(d, f'00100{i}.SZ', lane, float(i), .8, .9)
                               for d in ['20230103','20240103','20250103','20260105']
                               for i,lane in enumerate(['B1','B2','B3'])])
    predictions.loc[len(predictions)] = case('20230104', '009999.SZ', 'B1', 999., .49, 1.)
    curves, summary, uniques = p.annual_calibrators(predictions,ab,b3)
    assert curves[2023,'B1'].tolist() == [0,1,2,3,4]
    assert curves[2024,'B1'].tolist() == [0,0,1,2,3,4]
    assert summary.loc[summary.year.eq(2024) & summary.lane.eq('B1'),'max_D'].item() == '20230103'
    assert summary.n.sum() == uniques['count'].sum()
    altered = predictions.copy()
    altered.loc[altered.D.ge('20240101'), ['rank_score','S_prob_gated','B_probability']] = 1000.
    changed, s2, _ = p.annual_calibrators(altered,ab,b3)
    pd.testing.assert_frame_equal(summary.loc[summary.year.le(2024)], s2.loc[s2.year.le(2024)], check_exact=True)
    for year in [2023,2024]:
        for lane in p.c.LANES:
            np.testing.assert_array_equal(curves[year,lane], changed[year,lane])
    duplicate = pd.concat([predictions, predictions.iloc[:1]])
    with pytest.raises(ValueError, match='OVERLAP'):
        p.annual_calibrators(duplicate,ab,b3)


def test_q80_gate_before_top3_same_ready_pool_dedup_and_ties():
    day='20230103'
    rows = [case(day, '000000.SZ','B1',.799), case(day,'000001.SZ','B1',.8),
            case(day,'000002.SZ','B2',.8), case(day,'000003.SZ','B3',99.,.5,.5),
            case(day,'000001.SZ','B3',99.,.5,.5), case(day,'000004.SZ','B1',.8)]
    rows.append(case(day, '000005.SZ','B3',99.,.49,1.))
    frame=pd.DataFrame(rows)
    thresholds=pd.DataFrame([dict(year=2023,B1_q80=.8,B2_q80=.8)])
    calibrators={(2023,'B1'):np.array([.8]), (2023,'B2'):np.array([.8]), (2023,'B3'):np.array([.25])}
    selected,audit=p.percentile_picks(frame,thresholds,calibrators)
    assert selected.canonical_security_id.tolist()==['000001.SZ','000002.SZ','000003.SZ']
    assert selected.lane.tolist()==['B1','B2','B3']
    assert selected.percentile_score.eq(.5).all()
    assert not audit.loc[audit.canonical_security_id.eq('000000.SZ'),'pass_raw_q80'].item()
    assert '000005.SZ' not in set(audit.canonical_security_id)
    old = hybrid_picks(frame,thresholds,pd.DataFrame({'D':[day], 'daily_K':[999]}))
    assert set(old.canonical_security_id)==set(audit.loc[audit.pass_raw_q80,'canonical_security_id'])
    # B3 raw RF authenticates hard eligibility but never changes B3 product ordering.
    changed=frame.copy(); changed.loc[changed.lane.eq('B3'),'rank_score']=-999.
    changed_picks,_=p.percentile_picks(changed,thresholds,calibrators)
    assert selected[['episode_id','rank_position']].equals(changed_picks[['episode_id','rank_position']])


def test_new_scores_do_not_change_original_engine_defaults_or_failed_slot_rules():
    s=pd.bdate_range('2022-12-30',periods=10).strftime('%Y%m%d').tolist()
    codes=['000001.SZ','000002.SZ']
    risk={d:dict(strict_state='RISK_ON',strict_cap=1.) for d in s}
    bars={code:{d:dict(open=10.,high=11.,low=9.,close=10.,vol=10.,tradeable_basic=1.,
                      zge_yellow_line=1.,limit_up_approx=0.,limit_down_approx=0.) for d in s} for code in codes}
    bars[codes[1]][s[2]].update(vol=0.)
    picks=pd.DataFrame([case(s[1],code) for code in codes]); picks['rank_position']=[1,2]
    picks['percentile_score']=[.99,.9]
    expected_n,expected_l=base.portfolio(as_picks(picks),bars,s,risk,'STRICT','ALL',3,asof=s[8])
    stripped=picks.drop(columns='percentile_score')
    n,l=base.portfolio(as_picks(stripped),bars,s,risk,'STRICT','ALL',3,asof=s[8])
    pd.testing.assert_frame_equal(n,expected_n,check_exact=True)
    pd.testing.assert_frame_equal(l,expected_l,check_exact=True)
    assert l.status.tolist()==['CLOSED','FAILED_ENTRY']
    assert n.loc[n.D.eq(s[2]),'entries'].item()==1
    assert np.isclose(l.allocation.iloc[0],1/6)


def test_reused_arms_preserve_every_numeric_value_and_drop_timing_arms():
    frame=pd.DataFrame({'scenario':['BASELINE_STRICT','TIMING_ONLY','ROUTING_ONLY','TIMING_ROUTING'],
                        'config_id':[0,1,2,3], 'NAV':[1.2,1.1,.8,.9], 'rank_score':[.2,.3,.4,.5]})
    reused=p.rename_reused(frame)
    assert reused.scenario.tolist()==['BASELINE_RF','ORIGINAL_HYBRID']
    assert reused.config_id.tolist()==[0,1]
    pd.testing.assert_frame_equal(reused[['NAV','rank_score']].reset_index(drop=True),
                                  frame.iloc[[0,2]][['NAV','rank_score']].reset_index(drop=True),check_exact=True)
