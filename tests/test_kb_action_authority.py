import json

from ops.kb_action_authority import action_rule_sha256, project_action


def test_actual_stock_states_use_same_authority_and_keep_unknown_context():
    junda = dict(kb_b1=False, kb_b2=False, kb_b3=False, kb_b1_j=98.05,
                 kb_bull_rope_status='牛绳断', kb_white_cross_down=False, kb_macd_veto=True,
                 kb_brick_action='持有', kb_hold_score=None, kb_hold_score_min=4, kb_hold_score_max=5)
    gold = dict(kb_b1=True, kb_b2=False, kb_b3=False, kb_b1_j=35.4,
                kb_bull_rope_status='牵牛', kb_white_cross_down=False, kb_macd_veto=False,
                kb_brick_action='禁止抄底', kb_hold_score=None, kb_hold_score_min=1,
                kb_hold_score_max=2, user_v1_sell_signal_daily=1)
    a, b = project_action(junda), project_action(gold)
    assert (a['kb_action_no_position'], a['kb_action_with_position']) == ('等回调', '持有')
    assert a['kb_action_with_position_status'] == 'CONFLICTING_OBSERVATIONS'
    assert '不表示今日刚发生下穿' in ' '.join(json.loads(a['kb_action_reasons']))
    assert '不以J>90单独认定放飞' in ' '.join(json.loads(a['kb_action_reasons']))
    assert (b['kb_action_no_position'], b['kb_action_with_position']) == ('等回调', '卖出')
    assert '不等同于尚未统一定义的KB S1' in ' '.join(json.loads(b['kb_action_reasons']))
    assert a['kb_action_rule_sha256'] == b['kb_action_rule_sha256'] == action_rule_sha256()


def test_tristate_score_and_rope_do_not_become_default_buy_or_sell():
    row = dict(kb_b1=False, kb_b2=False, kb_b3=False, kb_bull_rope_status='牵牛',
               kb_white_cross_down=False, kb_macd_veto=False, kb_brick_action='持有',
               kb_hold_score=None, kb_hold_score_min=4, kb_hold_score_max=5)
    assert project_action(row)['kb_action_with_position'] == '持有'
    assert project_action({**row, 'kb_bull_rope_status':'金叉'})['kb_action_with_position'] == '持有'
    assert project_action({**row, 'kb_bull_rope_status':None})['kb_action_with_position'] is None
    assert project_action({**row, 'kb_hold_score_min':2, 'kb_hold_score_max':4})['kb_action_with_position'] is None
    assert project_action({**row, 'kb_hold_score':0})['kb_action_with_position'] is None
    assert project_action({**row, 'kb_white_cross_down':True})['kb_action_with_position'] == '卖出'
    assert project_action({**row, 'kb_brick_action':'减仓'})['kb_action_with_position'] == '放飞'
    assert project_action({**row, 'kb_hold_score':3, 'kb_hold_score_min':3, 'kb_hold_score_max':3})['kb_action_with_position'] == '放飞'
    assert project_action({**row, 'kb_b1':None})['kb_action_no_position'] is None
    hit = project_action({**row, 'kb_b1':True})
    assert hit['kb_action_no_position'] == '等回调' and hit['kb_action_no_position_status'] == 'UNKNOWN_BUY_FILTERS'
    assert project_action({**row, 'kb_b1':True, 'kb_brick_action':'禁止抄底'})['kb_action_no_position'] == '等回调'


def test_persisted_float_sell_signal_matches_integer_without_coercing_other_values():
    row = dict(kb_b1=False, kb_b2=False, kb_b3=False, kb_bull_rope_status='牵牛',
               kb_white_cross_down=False, kb_macd_veto=False, kb_brick_action='持有',
               kb_hold_score=None, kb_hold_score_min=4, kb_hold_score_max=5)
    integer = project_action({**row, 'user_v1_sell_signal_daily': 1})
    floating = project_action({**row, 'user_v1_sell_signal_daily': 1.0})
    assert floating == integer
    assert floating['kb_action_with_position_status'] == 'CONFLICTING_OBSERVATIONS'
    assert '原式卖点独立展示' in floating['kb_action_reasons']
    for value in (0, 0.0, 1.01, '1', None, float('nan')):
        observed = project_action({**row, 'user_v1_sell_signal_daily': value})
        assert observed['kb_action_with_position_status'] == 'OBSERVED_SCORE_HOLD_CONDITIONAL'
        assert '原式卖点独立展示' not in observed['kb_action_reasons']
