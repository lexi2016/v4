from copy import deepcopy

import pytest

from v4.manager_workbench.us_mapping_replay_metrics import (
    adjustment_available, candidate_top10, continuous_curve, evaluate_day, frozen_split, rank_ic,
)

SESSIONS = ['20261012', '20261013', '20261014', '20261015', '20261016', '20261020',
            '20261021', '20261022', '20261023', '20261026', '20261027', '20261028']


def inputs():
    return dict(signal_date=SESSIONS[0], sessions=SESSIONS,
        selected_symbols=['HK.00001', 'HK.00001', 'HK.00002'],
        bars={symbol: {day: {'open': 100, 'close': 100 + i * n} for i, day in enumerate(SESSIONS)}
              for symbol, n in [('HK.00001', 10), ('HK.00002', -2), ('HK.00003', 0)]},
        complete=True, pending_count=0, pit_price_verified=True,
        signal_cutoff='2026-10-12T16:10:00+08:00',
        benchmark={'universe_ref': 'HK_CONNECT_FULL_MARKET', 'verification': 'VERIFIED',
                   'effective_from': '20261001', 'effective_through': '20261031',
                   'available_at': '2026-10-12T09:00:00+08:00', 'source_sha256': 'a' * 64,
                   'symbols': ['HK.00001', 'HK.00002', 'HK.00003']})


def test_signal_following_open_to_125_session_close_not_signal_close():
    value = evaluate_day(**inputs())
    assert value['unique_selected'] == ['HK.00001', 'HK.00002']
    assert value['daily_1d_return'] == pytest.approx(.04)
    assert value['horizons']['1']['mean'] == pytest.approx(.04)
    assert value['horizons']['2']['mean'] == pytest.approx(.08)
    assert value['horizons']['5']['mean'] == pytest.approx(.20)
    assert value['horizons']['5']['exit_date'] == '20261020'  # HK holiday19 is not a session.
    assert value['horizons']['1']['positive_fraction'] == .5
    assert value['horizons']['1']['median'] == pytest.approx(.04)
    assert value['horizons']['1']['benchmark_mean'] == pytest.approx(.08 / 3)
    assert value['horizons']['1']['excess'] == pytest.approx(.04 - .08 / 3)
    assert value['horizons']['2']['interpretation'] == 'OVERLAPPING_EVENT_RETURNS_NOT_PORTFOLIO'


def test_pending_and_missing_zero_are_na_only_genuine_empty_is_cash0():
    data = inputs(); data['selected_symbols'] = []
    assert evaluate_day(**data)['daily_1d_return'] == 0
    for field, val in [('pending_count', 1), ('complete', False), ('pit_price_verified', False)]:
        current = deepcopy(data); current[field] = val
        value = evaluate_day(**current)
        assert value['daily_1d_return'] is None
        assert value['horizons']['1']['status'] == 'NOT_EVALUABLE'


def test_pending_other_names_does_not_change_known_selected_event_returns():
    data = inputs(); data['pending_count'] = 12
    assert evaluate_day(**data)['daily_1d_return'] == pytest.approx(.04)


def test_unknown_price_or_completion_status_is_not_verified_truthiness():
    for key in ('complete', 'pit_price_verified', 'entry_timestamp_verified'):
        data = inputs(); data[key] = 'UNKNOWN'
        assert evaluate_day(**data)['daily_1d_return'] is None


@pytest.mark.parametrize('field', ['open', 'close'])
def test_one_selected_missing_price_invalidates_whole_day_without_reweighting(field):
    data = inputs(); del data['bars']['HK.00002']['20261013'][field]
    value = evaluate_day(**data)
    assert value['daily_1d_return'] is None
    assert value['horizons']['1']['mean'] is None
    assert 'SELECTED_ENTRY_OR_EXIT_MISSING' in value['horizons']['1']['reasons']
    assert len(value['horizons']['1']['events']) == 1  # diagnostics only


def test_curve_na_breaks_segments_and_does_not_bridge_missing_dates():
    values = {SESSIONS[0]: .10, SESSIONS[1]: None, SESSIONS[2]: .20, SESSIONS[3]: 0}
    segments = continuous_curve(SESSIONS[:4], values)
    assert len(segments) == 2
    assert segments[0]['equity'] == pytest.approx([1.1])
    assert segments[1]['equity'] == pytest.approx([1.2, 1.2])
    assert segments[1]['initial_equity'] == 1


def test_chronological_final20_percent_ceiling_and_five_session_purge():
    split = frozen_split(SESSIONS, SESSIONS)
    assert split['sealed_dates'] == SESSIONS[-3:]
    assert split['purged_dates'] == SESSIONS[4:9]
    assert split['train_dates'] == SESSIONS[:4]
    assert frozen_split(SESSIONS, [])['sealed_dates'] == []
    with pytest.raises(ValueError, match='SPLIT_DATES_INVALID'):
        frozen_split(SESSIONS, ['20990101'])


def test_current_or_late_membership_cannot_be_historical_benchmark():
    for key, val in [('universe_ref', 'CURRENT_667_MAPPING'), ('effective_from', '20261020'),
                     ('available_at', '2026-10-14T09:00:00+08:00')]:
        data = inputs(); data['benchmark'][key] = val
        value = evaluate_day(**data)
        assert value['horizons']['1']['benchmark_mean'] is None
        assert value['horizons']['1']['excess'] is None
        assert 'EFFECTIVE_DATED_BENCHMARK_UNAVAILABLE' in value['horizons']['1']['reasons']


def test_adjustment_requires_effective_and_available_before_asof():
    event = {'applied': True, 'effective_at': '2026-10-12T00:00:00+08:00',
             'available_at': '2026-10-11T12:00:00+08:00'}
    cutoff = '2026-10-12T16:10:00+08:00'
    assert adjustment_available([event], as_of=cutoff)
    for field in ('effective_at', 'available_at'):
        late = {**event, field: '2026-10-13T00:00:00+08:00'}
        assert not adjustment_available([late], as_of=cutoff)
    assert not adjustment_available([{'applied': True}], as_of=cutoff)


def test_intraday_without_entry_timestamp_is_engineering_only():
    data = inputs(); data['entry_timestamp_verified'] = False
    value = evaluate_day(**data)
    assert value['daily_1d_return'] is None
    assert 'ENTRY_TIMESTAMP_UNVERIFIED' in value['horizons']['1']['reasons']


def test_ic_needs_same_date_universe_meaningful_count_and_variation():
    assert rank_ic({'a': 1, 'b': 2}, {'a': 1, 'b': 2}, same_date_universe_verified=True) is None
    scores, returns = {'a': 1, 'b': 2, 'c': 3}, {'a': 3, 'b': 2, 'c': 1}
    assert rank_ic(scores, returns, same_date_universe_verified=True) == pytest.approx(-1)
    assert rank_ic(scores, returns, same_date_universe_verified=False) is None
    assert rank_ic(dict.fromkeys(scores, 1), returns, same_date_universe_verified=True) is None
    assert rank_ic({'a': 1, 'b': 1, 'c': 3}, returns, same_date_universe_verified=True) == pytest.approx(-.8660254038)


def test_original_order_top10_does_not_rerank_or_truncate_candidate_source():
    symbols = ['z', 'z'] + [str(n) for n in range(20)]
    original = list(symbols)
    assert candidate_top10(symbols) == ['z'] + [str(n) for n in range(9)]
    assert symbols == original
