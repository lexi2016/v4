import math
import pytest

from ops.kb_yidong_authority import FIELDS, project_yidong_history, rule_sha256


def bars():
    return [dict(trade_date=20200000+i, open=10., close=11., volume=100., pct_chg=1.,
                 ma60=10., zge_yellow_line=10.) for i in range(1, 71)]


def test_confirmed_thresholds_compare_prior_five_and_keep_phase_unknown():
    rows=bars();rows[-1].update(volume=200.,pct_chg=2.)
    out=project_yidong_history(rows)
    assert out[63]['kb_yidong_is'] is None
    assert out[-1]['kb_yidong_is'] is True
    assert out[-1]['kb_yidong_james'] is False and out[-1]['kb_yidong_type']=='徐杰级'
    assert out[-1]['kb_yidong_vol_ratio_5']==2 and out[-1]['kb_yidong_bullish_count_5']==5
    assert out[-1]['kb_yidong_peak_ratio_5_20']==2
    assert out[-1]['kb_yidong_ma60_distance_pct']==pytest.approx(10)
    assert out[-1]['kb_yidong_yellow_distance_pct'] is None
    assert out[-1]['kb_yidong_phase_anchor_date'] is None
    assert out[-1]['kb_yidong_phase_status']=='ANCHOR_RULE_NOT_QUANTIFIED'
    assert out[-1]['kb_yidong_rule_sha256']==rule_sha256()
    rows[-1].update(volume=300.,pct_chg=5.)
    james=project_yidong_history(rows)[-1]
    assert james['kb_yidong_james'] is True and james['kb_yidong_type']=='詹姆斯级'
    assert set(james)==set(FIELDS)
    rows[-2]['open']=12.;rows[-3]['open']=12.;rows[-4]['open']=12.
    james=project_yidong_history(rows)[-1]
    assert james['kb_yidong_james'] is False and james['kb_yidong_type']=='徐杰级'


def test_invalid_inputs_and_prefix_revision_preserve_unknown():
    rows=bars();base=project_yidong_history(rows[:-1]);extended=project_yidong_history(rows)
    assert base==extended[:-1]
    rows[-1]['volume']=0
    invalid=project_yidong_history(rows)[-1]
    assert invalid['kb_yidong_is'] is None and invalid['kb_yidong_james'] is None
    assert invalid['kb_yidong_status']=='INVALID_PRICE_OR_VOLUME'
    rows[-1]['volume']=300.;rows[-1]['pct_chg']=5.;rows[-2]['open']=math.nan
    partial=project_yidong_history(rows)[-1]
    assert partial['kb_yidong_is'] is True and partial['kb_yidong_james'] is None
    assert partial['kb_yidong_type'] is None and partial['kb_yidong_status']=='PARTIAL_CANDLE_INPUT'
    rows[-1]['trade_date']=rows[-2]['trade_date']
    with pytest.raises(ValueError,match='DATES_NOT_STRICTLY_INCREASING'):
        project_yidong_history(rows)
