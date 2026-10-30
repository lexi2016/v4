import copy
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from domains import research_daily_statistics as stats
from domains.research_event_case_cache import EventCaseCache


@pytest.fixture
def fixture(tmp_path):
    calendar = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(310)]
    rows = [dict(date=day, close=float(i + 10)) for i, day in enumerate(calendar)]
    identity = dict(symbol='001328.SZ', market='SZ', source_authority='existing_panel', basis='QFQ_ASOF', rule_sha256='a'*64, formula_sha256='b'*64)
    cache = EventCaseCache(tmp_path/'events.sqlite3')
    kwargs = dict(identity=identity, calendar=calendar, close_rows=rows, event_dates=[calendar[250], calendar[280]], asof=calendar[290])
    yield cache, kwargs
    cache.close()


def assert_original(value, kwargs):
    index = {day: i for i, day in enumerate(kwargs['calendar'])}
    for key, n in [('d2', 2), ('d5', 5)]:
        expected = stats._horizon_statistics(sorted(kwargs['event_dates']), horizon_sessions=n, calendar=kwargs['calendar'], calendar_index=index, asof_index=index[kwargs['asof']], close_by_date={row['date']: row['close'] for row in kwargs['close_rows'] if row['date'] <= kwargs['asof']}, case_limit=10000)
        actual = value['horizons'][key]
        for field, content in expected.items():
            if field != 'cases':
                assert actual[field] == content
        for a, e in zip(actual['cases'], expected['cases']):
            assert {key: a[key] for key in e} == e


def test_persistent_generation_asof_append_and_bins_do_not_recompute(fixture):
    cache, kwargs = fixture
    first = cache.build(**kwargs)
    assert first['cache']['return_evaluations'] == 4
    assert_original(first, kwargs)
    path = cache.db.execute('PRAGMA database_list').fetchone()[2]
    cache.db.close()
    cache.db = __import__('sqlite3').connect(path)
    changed = copy.deepcopy(kwargs)
    changed['identity'].update(generation='new', asof='new', contract='new')
    changed['asof'] = changed['calendar'][291]
    changed['calendar'].append('2025-01-01')
    with patch.object(stats, '_evaluate_event_return', side_effect=AssertionError('must reuse')):
        repeated = cache.build(**changed, bucket_edges=(0., .5, 1.))
    assert repeated['cache']['return_evaluations'] == 0
    assert repeated['cache']['return_hits'] == 4
    assert repeated['cache']['percentile_evaluations'] == 1  # current asof only
    assert_original(repeated, changed)


def test_pair_revision_selectively_recomputes(fixture):
    cache, kwargs = fixture
    cache.build(**kwargs)
    revised = copy.deepcopy(kwargs)
    revised['close_rows'][252]['close'] = 30.
    value = cache.build(**revised)
    assert value['cache']['return_evaluations'] == 1
    assert value['cache']['return_hits'] == 3
    assert_original(value, revised)


def test_calendar_insertion_only_invalidates_affected_slice(fixture):
    cache, kwargs = fixture
    cache.build(**kwargs)
    revised = copy.deepcopy(kwargs)
    revised['calendar'].remove(revised['calendar'][253])
    value = cache.build(**revised)
    assert value['cache']['return_evaluations'] == 1  # first d5 only
    assert_original(value, revised)


def test_earlier_asof_never_exposes_cached_future_return(fixture):
    cache, kwargs = fixture
    cache.build(**kwargs)
    early = {**kwargs, 'asof': kwargs['calendar'][281]}
    value = cache.build(**early)
    assert value['cache']['return_evaluations'] == 2
    for horizon in value['horizons'].values():
        assert horizon['cases'][0]['status'] == 'not_matured'
        assert horizon['cases'][0]['return_pct'] is None
    assert_original(value, early)
    # Earlier read cannot erase the mature cache version.
    assert cache.build(**kwargs)['cache']['return_evaluations'] == 0


def test_immature_to_missing_to_filled_and_flat(fixture):
    cache, kwargs = fixture
    event = kwargs['calendar'][280]
    changed = {**copy.deepcopy(kwargs), 'event_dates': [event], 'asof': kwargs['calendar'][281]}
    cache.build(**changed)
    changed['asof'] = kwargs['calendar'][285]
    del changed['close_rows'][282]
    value = cache.build(**changed)
    assert value['cache']['return_evaluations'] == 2
    assert value['horizons']['d2']['cases'][0]['detail_status'] == 'MISSING_TARGET_BAR'
    changed['close_rows'].insert(282, dict(date=kwargs['calendar'][282], close=290.))
    value = cache.build(**changed)
    assert value['cache']['return_evaluations'] == 1
    assert value['horizons']['d2']['flat'] == 1
    assert value['horizons']['d2']['valid'] == 1
    assert_original(value, changed)


def test_causal_percentile_and_new_events(fixture):
    cache, kwargs = fixture
    first = cache.build(**kwargs)
    revised = copy.deepcopy(kwargs)
    revised['close_rows'][300]['close'] = 1e8  # future price irrelevant
    with patch.object(stats, '_evaluate_event_return', side_effect=AssertionError('must reuse')):
        value = cache.build(**revised)
    assert value['cache']['percentile_evaluations'] == 0
    assert value['horizons'] == first['horizons']
    revised['event_dates'].append(revised['calendar'][270])
    value = cache.build(**revised)
    assert value['cache']['return_evaluations'] == 2
    assert value['cache']['percentile_evaluations'] == 1
    assert_original(value, revised)


@pytest.mark.parametrize('field', ['symbol', 'market', 'source_authority', 'basis', 'rule_sha256', 'formula_sha256'])
def test_semantic_identity_invalidates(fixture, field):
    cache, kwargs = fixture
    cache.build(**kwargs)
    changed = copy.deepcopy(kwargs)
    if field in ('symbol', 'market'):
        changed['identity'].update(symbol='600000.SH', market='SH')
    else:
        changed['identity'][field] = 'revised'
    assert cache.build(**changed)['cache']['return_evaluations'] == 4


def test_original_percentile_parity_and_bin_change_no_return_calls(fixture):
    cache, kwargs = fixture
    value = cache.build(**kwargs)
    expected = stats.stratify_event_cases_by_prefix_percentile(close_rows=kwargs['close_rows'], event_cases={key: item['cases'] for key, item in value['horizons'].items()}, asof=kwargs['asof'])
    for key in ('d2', 'd5'):
        assert value['horizons'][key]['cases'] == expected['horizons'][key]['cases']
        assert value['horizons'][key]['conditional'] == expected['horizons'][key]['conditional']
    with patch.object(stats, '_evaluate_event_return', side_effect=AssertionError('must reuse')):
        changed = cache.build(**kwargs, bucket_edges=(0., .9, 1.))
    assert changed['cache']['return_evaluations'] == 0
    assert changed['cache']['percentile_evaluations'] == 0


def test_missing_event_bar_percentile_stays_unknown(fixture):
    cache, kwargs = fixture
    changed = copy.deepcopy(kwargs)
    changed['close_rows'].pop(250)
    value = cache.build(**changed)
    assert value['horizons']['d2']['cases'][1]['price_percentile'] is None
    assert value['horizons']['d2']['missing_price'] == 1
