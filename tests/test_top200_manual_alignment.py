from datetime import date, timedelta

import pandas as pd
import pytest

from ops.kb_confirmed_gap import project_selected
from ops.kb_hold_score import apply_n_score, volume_component


def bars(count):
    rows=[];previous=20.0
    for i in range(count):
        close=round(20+i*.01,2)
        rows.append({'ts_code':'600187.SH','trade_date':int((date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d')),
                     'open':close-.1,'high':close+.2,'low':close-.2,'close':close,'vol':1000.,
                     'pre_close':previous,'pct_chg':round((close/previous-1)*100,2),
                     'kb_double_gun':False if i>=23 else None,'kb_violence_k':False if i>=20 else None,
                     'kb_yidong_vol_ratio_5':1. if i>=5 else None})
        previous=close
    return pd.DataFrame(rows)


def test_confirmed_volume_branch_keeps_other_cases_unknown():
    bar={'open': 9.0,'high': 11.0,'low': 8.0,'close': 10.0,'volume': 4.0}
    assert volume_component(bar)==(True,None)
    assert volume_component({**bar,'open':10.5})==(None,'RULE_NOT_QUANTIFIED')
    assert volume_component({**bar,'volume':0})==(None,'INVALID_VOLUME_INPUT')
    assert volume_component({**bar,'low':10.1})==(None,'INVALID_OHLC_INPUT')


def test_existing_invalid_input_isolated_to_affected_components():
    frame=bars(30);frame.loc[29,'low']=-0.1;frame.loc[29,'kb_violence_k']=True
    with pytest.raises(ValueError,match='CONFIRMED_GAP_EXISTING_SIGNAL_INPUT_CONFLICT'):
        project_selected(frame,[29])
    values,diag=project_selected(frame,[29],allow_existing_input_conflict=True)[29]
    assert values['kb_violence_k_type'] is None and values['kb_violence_k_body'] is None
    assert diag['kb_violence_k_components_status']=='EXISTING_SIGNAL_INPUT_CONFLICT'
    assert values['kb_brick_trend'] is None
    assert frame.loc[29,'kb_violence_k'] is True or bool(frame.loc[29,'kb_violence_k'])


def test_nonpositive_rebuild_denominator_is_unknown():
    frame=bars(124)
    for i in range(109):
        frame.loc[i,['open','high','low','close','pre_close','pct_chg']]=[-100.,-99.,-101.,-100.,-100.,0.]
    frame.loc[109,'pre_close']=-100.
    result,diag=project_selected(frame,[123],allow_existing_input_conflict=True)[123]
    assert result['kb_rebuild'] is None
    assert diag['kb_rebuild_reason']=='INVALID_CLOSE_IN_REQUIRED_WINDOW'


def test_n_scoped_score_requires_matching_rule_and_explicit_membership():
    code='600187.SH';rule='a'*64;helper='b'*64
    source=[{'trade_date':'20261030'}]
    score=[{'kb_hold_close_up':True,'kb_hold_above_bbi':False,'kb_hold_volume_ok':True,
            'kb_hold_trend_up':None,'kb_hold_j_not_dead':True}]
    n=[{'ts_code':code,'trade_date':'20261030','kb_hold_trend_up':False,
        'kb_hold_trend_up_reason':'STRUCTURE_NOT_RISING',
        'kb_n_structure':{'state':'STRUCTURE_NOT_RISING','rule_sha256':rule,'helper_sha256':helper}}]
    with pytest.raises(ValueError,match='HOLD_N_ROW_SET_CONFLICT'):
        apply_n_score(code,source,score,n,rule_sha256=rule,helper_sha256=helper)
    result=apply_n_score(code,source,score,n,rule_sha256=rule,helper_sha256=helper,allowed_symbols=[code])
    assert (result[0]['kb_hold_score'],result[0]['kb_hold_score_min'],result[0]['kb_hold_score_max'])==(3,3,3)
    assert score[0]['kb_hold_trend_up'] is None
