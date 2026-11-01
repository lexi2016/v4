import json
from datetime import date, timedelta

import pytest

from ops.kb_n_structure import n_prefix_sha256, project_n_history


CODE = '301048.SZ'
IDENTITY = {'input_sha256': '1' * 64, 'rule_sha256': '2' * 64, 'helper_sha256': '3' * 64,
            'calendar_sha256': '4' * 64, 'price_basis_sha256': '5' * 64,
            'price_basis': 'QFQ_ASOF', 'generation_id': 'test-generation-1'}


def day(index):
    return (date(2024, 1, 1) + timedelta(days=index)).strftime('%Y%m%d')


def interpolated(anchors):
    values = []
    for index in range(anchors[-1][0] + 1):
        for (left, a), (right, b) in zip(anchors, anchors[1:]):
            if left <= index <= right:
                value = a + (b - a) * (index - left) / (right - left)
                values.append(value)
                break
    return [{'trade_date': day(i), 'ts_code': CODE, 'high': x + 1, 'low': x - 1, 'close': x}
            for i, x in enumerate(values)]


def trend_rows(low2=10, high2=18):
    return interpolated([(0, 12), (5, 8), (11, 15), (17, low2), (23, high2),
                         (29, high2 - 3), (35, 11), (41, 19), (47, 15)])


def run(rows, identity=IDENTITY):
    return project_n_history(CODE, rows, identity=identity)


def test_rising_trend_is_known_only_after_the_last_right_five_bars():
    rows = trend_rows()
    result, _ = run(rows)
    assert result[27]['kb_hold_trend_up'] is None
    known = result[28]
    assert known['kb_hold_trend_up'] is True
    info = known['kb_n_structure']
    assert [(info[p]['event_date'], info[p]['confirmed_at']) for p in ('L1', 'H1', 'L2', 'H2')] == [
        (day(5), day(10)), (day(11), day(16)), (day(17), day(22)), (day(23), day(28))]
    assert info['structure_known_at'] == day(28)
    assert info['first_breakout_at'] is None
    assert info['L1']['price'] == 7 and info['H2']['price'] == 19
    assert all(row['kb_hold_trend_up'] is None for row in result[:28])


def test_high_low_high_low_order_is_also_valid_when_both_extremes_rise():
    rows = interpolated([(0, 12), (5, 16), (11, 8), (17, 19), (23, 10), (29, 14)])
    result, _ = run(rows)
    assert result[27]['kb_hold_trend_up'] is None
    assert result[28]['kb_hold_trend_up'] is True
    info = result[28]['kb_n_structure']
    assert [info[p]['event_date'] for p in ('H1', 'L1', 'H2', 'L2')] == [
        day(5), day(11), day(17), day(23)]


@pytest.mark.parametrize('low2,high2', [(7, 14), (10, 15), (8, 18)])
def test_fully_confirmed_descending_or_equal_extremes_are_not_rising(low2, high2):
    result, _ = run(trend_rows(low2=low2, high2=high2))
    assert result[28]['kb_hold_trend_up'] is False
    assert result[28]['kb_hold_trend_up_reason'] == 'STRUCTURE_NOT_RISING'


def test_last_equal_extreme_wins_and_right_five_are_required():
    values = [12, 11, 10, 9, 8, 7, 7, 8, 9, 10, 11, 12]
    rows = [{'trade_date': day(i), 'high': p + 1, 'low': p - 1, 'close': p}
            for i, p in enumerate(values)]
    result, _ = run(rows)
    assert result[10]['kb_n_structure']['L2']['event_date'] is None
    assert result[11]['kb_n_structure']['L2'] == {
        'event_date': day(6), 'confirmed_at': day(11), 'price': 6.0}
    assert result[10]['kb_n_structure']['available_bars'] == 11
    assert result[10]['kb_n_structure']['confirmed_swings'] == 0


def test_same_direction_retains_more_extreme_or_later_equal_point():
    rows = []
    for i in range(29):
        low = 10 + i * 0.01
        high = {5: 50, 11: 55, 17: 54, 23: 55}.get(i, 30)
        rows.append({'trade_date': day(i), 'high': high, 'low': low, 'close': low + 1})
    result, _ = run(rows)
    assert result[10]['kb_n_structure']['H2']['event_date'] == day(5)
    assert result[16]['kb_n_structure']['H2']['event_date'] == day(11)
    assert result[22]['kb_n_structure']['H2']['event_date'] == day(11)
    assert result[28]['kb_n_structure']['H2']['event_date'] == day(23)
    assert result[28]['kb_hold_trend_up'] is None


def test_same_bar_high_and_low_is_ambiguous_until_four_new_confirmed_swings():
    rows = [{'trade_date': day(i), 'high': 20, 'low': 10, 'close': 15} for i in range(11)]
    rows[5] = {'trade_date': day(5), 'high': 50, 'low': 5, 'close': 15}
    path = interpolated([(0, 12), (6, 8), (12, 15), (18, 10), (24, 18), (30, 14)])
    rows.extend({**x, 'trade_date': day(i + 10)} for i, x in enumerate(path) if i > 0)
    result, _ = run(rows)
    assert result[10]['kb_hold_trend_up_reason'] == 'AMBIGUOUS_SAME_BAR_PIVOT'
    assert result[10]['kb_n_structure']['confirmed_swings'] == 0
    assert all(x['kb_hold_trend_up'] is None for x in result[10:39])
    assert result[39]['kb_hold_trend_up'] is True
    assert result[39]['kb_n_structure']['structure_known_at'] == day(39)


def test_intraday_low_touch_does_not_break_but_strict_close_below_does():
    rows = trend_rows()[:29]
    rows.append({'trade_date': day(29), 'high': 11, 'low': 8.5, 'close': 9.5})
    rows.append({'trade_date': day(30), 'high': 10, 'low': 8, 'close': 9})
    rows.append({'trade_date': day(31), 'high': 10, 'low': 8, 'close': 8.999999999})
    rows.append({'trade_date': day(32), 'high': 11, 'low': 8.5, 'close': 9.5})
    result, _ = run(rows)
    assert result[29]['kb_hold_trend_up'] is True
    assert result[30]['kb_hold_trend_up'] is True
    assert result[31]['kb_hold_trend_up'] is False
    assert result[31]['kb_hold_trend_up_reason'] == 'BROKEN_BY_CLOSE'
    assert result[32]['kb_hold_trend_up'] is True


def test_a_close_below_one_low_cannot_replace_four_confirmed_swings():
    rows = trend_rows()[:11]
    rows.append({'trade_date': day(11), 'high': 8, 'low': 5, 'close': 6})
    result, _ = run(rows)
    assert result[10]['kb_n_structure']['confirmed_swings'] == 1
    assert result[11]['kb_hold_trend_up'] is None
    assert result[11]['kb_hold_trend_up_reason'] == 'INSUFFICIENT_CONFIRMED_SWINGS'


def test_invalid_bar_breaks_prefix_and_never_becomes_false_or_suspension():
    rows = trend_rows()[:40]
    rows[29] = {**rows[29], 'high': None}
    result, _ = run(rows)
    assert result[28]['kb_hold_trend_up'] is True
    assert result[29]['kb_hold_trend_up'] is None
    assert result[29]['kb_hold_trend_up_reason'] == 'INVALID_INPUT'
    assert result[29]['kb_n_structure']['available_bars'] == 0
    assert all(row['kb_hold_trend_up'] is None for row in result[29:])
    assert 'SUSPEND' not in json.dumps(result)


def test_restart_append_and_revision_match_each_full_prefix_without_backfill():
    rows = trend_rows()
    full, final = run(rows)
    split = 12
    prefix, checkpoint = run(rows[:split])
    loaded = json.loads(json.dumps(checkpoint))
    digest = n_prefix_sha256(CODE, rows[:split])
    suffix, resumed = project_n_history(CODE, rows[split:], identity=IDENTITY,
                                        checkpoint=loaded, expected_prefix_sha256=digest)
    assert prefix + suffix == full
    assert resumed == final
    for i in range(len(rows)):
        assert run(rows[:i + 1])[0][-1] == full[i]
    revised = [dict(row) for row in rows]
    revised[15].update(high=revised[15]['high'] + 0.7, low=revised[15]['low'] + 0.7,
                       close=revised[15]['close'] + 0.7)
    new_identity = {**IDENTITY, 'input_sha256': '6' * 64}
    revision_full, revision_final = run(revised, new_identity)
    revision_tail, revision_state = project_n_history(
        CODE, revised[split:], identity=new_identity, checkpoint=loaded, expected_prefix_sha256=digest)
    assert revision_tail == revision_full[split:]
    assert revision_state == revision_final
    assert n_prefix_sha256(CODE, rows[:16]) != n_prefix_sha256(CODE, revised[:16])
    _, stale = run(rows[:20])
    with pytest.raises(ValueError, match='PREFIX_CONFLICT'):
        project_n_history(CODE, revised[20:], identity=new_identity, checkpoint=stale,
                          expected_prefix_sha256=n_prefix_sha256(CODE, revised[:20]))


def test_checkpoint_rejects_tamper_wrong_prefix_identity_and_unbound_cross_generation():
    rows = trend_rows()[:15]
    _, checkpoint = run(rows)
    digest = n_prefix_sha256(CODE, rows)
    corrupted = json.loads(json.dumps(checkpoint))
    corrupted['swings'] = []
    with pytest.raises(ValueError, match='INTEGRITY_CONFLICT'):
        project_n_history(CODE, [], identity=IDENTITY, checkpoint=corrupted, expected_prefix_sha256=digest)
    with pytest.raises(ValueError, match='PREFIX_CONFLICT'):
        project_n_history(CODE, [], identity=IDENTITY, checkpoint=checkpoint, expected_prefix_sha256='9' * 64)
    with pytest.raises(ValueError, match='IDENTITY_CONFLICT'):
        project_n_history(CODE, [], identity={**IDENTITY, 'calendar_sha256': '9' * 64},
                          checkpoint=checkpoint, expected_prefix_sha256=digest)
    for field in ('calendar_sha256', 'price_basis_sha256'):
        old_identity = {**IDENTITY, field: None}
        _, unbound = run(rows, old_identity)
        with pytest.raises(ValueError, match='CROSS_GENERATION_IDENTITY_UNBOUND'):
            project_n_history(CODE, [], identity={**old_identity, 'input_sha256': '6' * 64},
                              checkpoint=unbound, expected_prefix_sha256=digest)
        with pytest.raises(ValueError, match='CROSS_GENERATION_IDENTITY_UNBOUND'):
            project_n_history(CODE, [], identity={**old_identity, 'generation_id': 'test-generation-2'},
                              checkpoint=unbound, expected_prefix_sha256=digest)


def test_symbol_dates_and_invalid_observations_are_not_silently_filled():
    with pytest.raises(ValueError, match='SYMBOL_CONFLICT'):
        run([{'trade_date': day(0), 'ts_code': '002865.SZ', 'high': 2, 'low': 1, 'close': 1.5}])
    with pytest.raises(ValueError, match='DATES_NOT_UNIQUE_SORTED'):
        run([{'trade_date': day(0), 'high': 2, 'low': 1, 'close': 1.5}] * 2)
    invalid = [{'trade_date': day(0), 'high': 2, 'low': 3, 'close': 2.5},
               {'trade_date': day(2), 'high': 2, 'low': 1, 'close': 1.5}]
    out, _ = run(invalid)
    assert len(out) == 2
    assert out[0]['kb_hold_trend_up'] is None and out[0]['kb_hold_trend_up_reason'] == 'INVALID_INPUT'
    assert out[1]['trade_date'] == day(2)
    assert out[1]['kb_hold_trend_up'] is None
