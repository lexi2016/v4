import copy

import pytest

from ops.kb_hold_score import score_history, project_single_history, SUPPLEMENTAL_REASONS
from ops.kb_signal_authority import DailyData, _source_kdj


def bars(closes):
    return [{'trade_date': 20200000 + i, 'open': value - 0.2, 'close': value, 'high': value + 1, 'low': value - 1, 'volume': 100}
            for i, value in enumerate(closes, 1)]


def test_partial_score_preserves_subjective_components_and_existing_rows():
    source = bars([20 + i / 10 for i in range(30)])
    before = copy.deepcopy(source)
    answer = score_history(source)[-1]
    assert source == before
    assert answer['kb_hold_close_up'] is True and answer['kb_hold_above_bbi'] is True
    assert answer['kb_hold_volume_ok'] is True and answer['kb_hold_trend_up'] is None
    assert answer['kb_hold_volume_ok_reason'] is None and answer['kb_hold_trend_up_reason'] == 'RULE_NOT_QUANTIFIED'
    assert answer['kb_hold_j_not_dead'] is True
    assert (answer['kb_hold_score'], answer['kb_hold_score_min'], answer['kb_hold_score_max']) == (None, 4, 5)
    assert answer['kb_hold_score_status'] == 'PARTIAL_UNKNOWN'


def test_candle_component_awards_only_close_above_open():
    source = bars([20, 21, 20, 20, 20])
    source[1]['open'] = 21.5  # higher close than previous, but a bearish candle
    source[2]['open'] = 19.5  # lower close than previous, but a bullish candle
    source[3]['open'] = 20.0  # flat is a confirmed zero
    source[4]['open'] = None
    answer = score_history(source)
    assert answer[1]['kb_hold_close_up'] is True and answer[1]['kb_hold_volume_ok'] is False
    assert answer[1]['kb_hold_volume_ok_reason'] is None
    assert answer[2]['kb_hold_close_up'] is False and answer[2]['kb_hold_volume_ok'] is True
    assert answer[2]['kb_hold_volume_ok_reason'] is None
    assert answer[3]['kb_hold_volume_ok'] is False
    assert answer[4]['kb_hold_volume_ok'] is None and answer[4]['kb_hold_volume_ok_reason'] == 'INVALID_OPEN_CLOSE_INPUT'


@pytest.mark.parametrize('volume', [None, 0, -1, float('nan'), float('inf')])
def test_candle_score_does_not_depend_on_volume(volume):
    source = bars([20, 21])
    source[-1]['volume'] = volume
    result = score_history(source)[-1]
    assert result['kb_hold_volume_ok'] is True
    assert result['kb_hold_volume_ok_reason'] is None


@pytest.mark.parametrize('field', ['open','close'])
@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), True])
def test_candle_score_needs_finite_non_boolean_open_and_close(field,value):
    source=bars([20,21]);source[-1][field]=value
    result=score_history(source)[-1]
    assert result['kb_hold_volume_ok'] is None
    assert result['kb_hold_volume_ok_reason']=='INVALID_OPEN_CLOSE_INPUT'


def test_candle_score_does_not_depend_on_high_or_low():
    source=bars([20,21]);source[-1]['high']=None;source[-1]['low']=None
    result=score_history(source)[-1]
    assert result['kb_hold_volume_ok'] is True and result['kb_hold_volume_ok_reason'] is None


def test_j_state_matches_pinned_source_and_is_not_one_bar_cross():
    source = bars([30 + i / 8 for i in range(35)] + [34 - i / 5 for i in range(25)])
    actual = score_history(source)
    reference = [DailyData('000001.SZ', str(r['trade_date']), r['close'], r['high'], r['low'],
                           r['close'], 100, 0, 0) for r in source]
    for i in (8, 25, 40, 59):
        k, d, j = _source_kdj(reference[:i + 1])
        assert (actual[i]['kb_hold_k'], actual[i]['kb_hold_d'], actual[i]['kb_hold_j']) == (k, d, j)
        assert actual[i]['kb_hold_j_not_dead'] == (not (j < k and j < d))
    assert actual[-1]['kb_hold_j_not_dead'] is False
    assert actual[-2]['kb_hold_j_not_dead'] is False


def test_qfq_negative_prefix_matches_bound_kdj_without_relaxing_other_components():
    source = bars([-2 + i / 4 for i in range(30)])
    actual = score_history(source)
    reference = [DailyData('600000.SH', str(r['trade_date']), r['open'], r['high'], r['low'],
                           r['close'], 100, 0, 0) for r in source]
    k, d, j = _source_kdj(reference)
    assert (actual[-1]['kb_hold_k'], actual[-1]['kb_hold_d'], actual[-1]['kb_hold_j']) == (k, d, j)
    assert actual[-1]['kb_hold_j_not_dead'] == (not (j < k and j < d))
    assert actual[0]['kb_hold_volume_ok'] is True
    assert actual[0]['kb_hold_volume_ok_reason'] is None
    assert actual[0]['kb_hold_close_up'] is None


def test_close_and_bbi_use_finite_negative_and_zero_qfq_without_changing_formula():
    negative = bars([-24 + i for i in range(25)])
    result = score_history(negative)[-1]
    assert result['kb_hold_close_up'] is True
    assert result['kb_hold_above_bbi'] is True
    assert result['kb_hold_bbi'] == round(sum(sum(r['close'] for r in negative[-p:]) / p for p in (3,6,12,24)) / 4, 2)
    shifted = bars([26 + i for i in range(25)])
    other = score_history(shifted)[-1]
    assert (result['kb_hold_close_up'], result['kb_hold_above_bbi']) == (other['kb_hold_close_up'], other['kb_hold_above_bbi'])
    assert result['kb_hold_bbi'] == pytest.approx(other['kb_hold_bbi'] - 50)
    for close in (0.0, -1.0):
        equal = score_history(bars([close] * 24))[-1]
        assert equal['kb_hold_close_up'] is False
        assert equal['kb_hold_above_bbi'] is None and equal['kb_hold_above_bbi_reason'] == 'BBI_EQUALITY_UNRESOLVED'


@pytest.mark.parametrize('invalid', [None, float('nan'), float('inf'), 'not-a-number', True, False])
def test_close_and_bbi_keep_missing_nonfinite_and_boolean_inputs_unknown(invalid):
    source = bars([10.0 + i / 10 for i in range(25)])
    source[-1]['close'] = invalid
    result = score_history(source)[-1]
    assert result['kb_hold_close_up'] is None and result['kb_hold_close_up_reason'] == 'INVALID_CLOSE_INPUT'
    assert result['kb_hold_above_bbi'] is None and result['kb_hold_above_bbi_reason'] == 'INVALID_CLOSE_WINDOW'
    assert result['kb_hold_j_not_dead'] is None and result['kb_hold_j_not_dead_reason'] == 'INVALID_HLC_PREFIX'


def test_warmup_equality_and_invalid_prefix_remain_unknown():
    source = bars([20.0] * 30)
    answer = score_history(source)
    assert answer[0]['kb_hold_close_up'] is None
    assert answer[0]['kb_hold_close_up_reason'] == 'INSUFFICIENT_PRIOR_BAR'
    assert answer[7]['kb_hold_j_not_dead'] is None
    assert answer[-1]['kb_hold_above_bbi'] is None
    assert answer[-1]['kb_hold_above_bbi_reason'] == 'BBI_EQUALITY_UNRESOLVED'
    source[10]['low'] = None
    broken = score_history(source)
    assert broken[10]['kb_hold_j_not_dead'] is None and broken[-1]['kb_hold_j_not_dead'] is None
    assert broken[-1]['kb_hold_j_not_dead_reason'] == 'INVALID_HLC_PREFIX'
    assert broken[-1]['kb_hold_score'] is None


def test_duplicate_date_rejected():
    source = bars([10, 11])
    source[1]['trade_date'] = source[0]['trade_date']
    with pytest.raises(ValueError, match='DATES_NOT_UNIQUE_SORTED'):
        score_history(source)


def test_daily_single_projection_appends_revises_and_keeps_uncertain_s_fields():
    source = bars([20 + i / 10 for i in range(30)])
    for row, score in zip(source, score_history(source)):
        row['kb_b1_j'] = score['kb_hold_j']
    first = project_single_history('002865.SZ', source[:29])
    appended = project_single_history('002865.SZ', source)
    assert appended[:29] == first
    assert all(appended[-1][field] is None for field in SUPPLEMENTAL_REASONS)
    assert 'kb_hold_j' not in appended[-1]
    revised = copy.deepcopy(source)
    revised[-1]['close'] = source[-2]['close'] - 0.05
    revised[-1]['kb_b1_j'] = score_history(revised)[-1]['kb_hold_j']
    assert project_single_history('002865.SZ', revised)[-1]['kb_hold_close_up'] is False
    with pytest.raises(ValueError, match='SINGLE_STOCK_SCOPE_CONFLICT'):
        project_single_history('000001.SZ', source)


def test_bulk_feedback_keeps_bound_j_and_invalid_prefix_gates():
    from ops.research_panel_qfq import _bulk_feedback_projection

    source = bars([10 + i / 10 for i in range(12)])
    for row, score in zip(source, score_history(source)):
        row['kb_b1_j'] = score['kb_hold_j']
    assert _bulk_feedback_projection('000063.SZ', source)[-1]['kb_hold_j_not_dead'] is not None

    missing = copy.deepcopy(source)
    missing[-1]['kb_b1_j'] = None
    actual = _bulk_feedback_projection('000063.SZ', missing)[-1]
    assert actual['kb_hold_j_not_dead'] is None
    assert actual['kb_hold_j_not_dead_reason'] == 'BOUND_KB_J_UNAVAILABLE'
    assert actual['kb_hold_score'] is None

    mismatch = copy.deepcopy(source)
    mismatch[-1]['kb_b1_j'] += 1
    with pytest.raises(ValueError, match='BOUND_KB_J_MISMATCH'):
        _bulk_feedback_projection('000063.SZ', mismatch)

    adjusted = copy.deepcopy(source)
    adjusted[0].update(high=-1., low=-3., close=-2.)
    for row, score in zip(adjusted, score_history(adjusted)):
        row['kb_b1_j'] = score['kb_hold_j']
    assert _bulk_feedback_projection('000063.SZ', adjusted)[-1]['kb_hold_j_not_dead'] is not None

    invalid = copy.deepcopy(source)
    invalid[0].update(high=-3., low=-1., close=-2.)
    actual = _bulk_feedback_projection('000063.SZ', invalid)[-1]
    assert actual['kb_hold_j_not_dead'] is None
    assert actual['kb_hold_j_not_dead_reason'] == 'INVALID_HLC_PREFIX'

    with pytest.raises(ValueError, match='SINGLE_STOCK_SCOPE_CONFLICT'):
        _bulk_feedback_projection('000063.HK', source)
