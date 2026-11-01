import copy

import pytest

from ops.kb_hold_score import score_history, project_single_history, SUPPLEMENTAL_REASONS
from ops.kb_signal_authority import DailyData, _source_kdj


def bars(closes):
    return [{'trade_date': 20200000 + i, 'close': value, 'high': value + 1, 'low': value - 1}
            for i, value in enumerate(closes, 1)]


def test_partial_score_preserves_subjective_components_and_existing_rows():
    source = bars([20 + i / 10 for i in range(30)])
    before = copy.deepcopy(source)
    answer = score_history(source)[-1]
    assert source == before
    assert answer['kb_hold_close_up'] is True and answer['kb_hold_above_bbi'] is True
    assert answer['kb_hold_volume_ok'] is None and answer['kb_hold_trend_up'] is None
    assert answer['kb_hold_volume_ok_reason'] == answer['kb_hold_trend_up_reason'] == 'RULE_NOT_QUANTIFIED'
    assert answer['kb_hold_j_not_dead'] is True
    assert (answer['kb_hold_score'], answer['kb_hold_score_min'], answer['kb_hold_score_max']) == (None, 3, 5)
    assert answer['kb_hold_score_status'] == 'PARTIAL_UNKNOWN'


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
