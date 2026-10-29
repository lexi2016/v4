"""Focused synthetic checks for the pure R5 daily product predicates."""
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / 'domains' / 'research_daily_product.py'
SPEC = importlib.util.spec_from_file_location('research_daily_product_test_target', MODULE_PATH)
PRODUCT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PRODUCT)

QUALIFIED = 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
BASELINES = {'original': 'TRUE', 'nav_pullback': 'TRUE', 'nav_breakout': 'TRUE'}


def bars(dates):
    return [
        {'trade_date': day, 'open': '100', 'high': '101', 'low': '99', 'close': '100', 'vol': '100'}
        for day in dates
    ]


def accepted_g4(day, *, close='103', prev_close='100'):
    return {
        'date': day,
        'close': close,
        'prev_close': prev_close,
        'correspondence_status': 'TRUE',
    }


def d28_calendar():
    day = date(2026, 8, 3)
    end = date(2026, 10, 28)
    days = []
    while day <= end:
        if day.weekday() < 5:
            days.append(int(day.strftime('%Y%m%d')))
        day += timedelta(days=1)
    return days


def call_product(calendar, data, signals, **kwargs):
    asof = kwargs.pop('asof', calendar[-1])
    return PRODUCT.evaluate_daily_product(
        symbol='600025.SH',
        asof=asof,
        fullprefix=data,
        exchange_calendar=calendar,
        original_breakout_by_date=signals,
        baseline_memberships=kwargs.pop('baseline_memberships', BASELINES),
        old_main_anchor_date=kwargs.pop('old_main_anchor_date', None),
        qualification_status=kwargs.pop('qualification_status', QUALIFIED),
        raw_g4_reference=kwargs.pop('raw_g4_reference', accepted_g4(calendar[-1])),
    )


class DailyProductPredicateTests(unittest.TestCase):
    def test_r5_d28_prior10_includes_tenth_exchange_session(self):
        calendar = d28_calendar()
        signal_date = calendar[-11]
        data = bars(calendar)
        data[-1]['vol'] = '80'
        result = call_product(calendar, data, {day: 'TRUE' if day == signal_date else 'FALSE' for day in calendar})
        self.assertEqual(result['prior10_dates'], [20261014, 20261015, 20261016, 20261019, 20261020, 20261021, 20261022, 20261023, 20261026, 20261027])
        self.assertEqual(result['new_prior10_key_gate'], 'TRUE')
        self.assertEqual(result['baseline']['nav_smallk'], 'TRUE')
        self.assertEqual(result['latest_prior_new_key_date'], signal_date)
        self.assertEqual(result['groups']['nav_smallk']['anchor_applicability'], 'TRUE')

    def test_prior10_uses_calendar_not_row_distance_or_eleven_day_key(self):
        calendar = d28_calendar()
        signal_date = calendar[-12]
        result = call_product(calendar, bars(calendar), {day: 'TRUE' if day == signal_date else 'FALSE' for day in calendar})
        self.assertEqual(result['prior10_dates'], calendar[-11:-1])
        self.assertEqual(result['new_prior10_key_gate'], 'FALSE')
        self.assertEqual(result['baseline']['nav_smallk'], 'FALSE')
        self.assertEqual(result['groups']['nav_smallk']['status'], 'FALSE')

    def test_missing_requested_calendar_bar_is_unknown_without_row_fallback(self):
        calendar = d28_calendar()
        missing = calendar[-5]
        data = bars([day for day in calendar if day != missing])
        data[-1]['vol'] = '80'
        result = call_product(calendar, data, {day: 'FALSE' for day in calendar})
        self.assertEqual(result['new_prior10_key_gate'], 'UNKNOWN')
        self.assertEqual(result['baseline']['nav_smallk'], 'UNKNOWN')
        self.assertEqual(result['input_coverage']['status'], 'UNKNOWN')

    def test_raw_g4_prev_close_is_not_replaced_by_qfq_bar_close(self):
        calendar = d28_calendar()
        data = bars(calendar)
        data[-2].update(open='198', high='202', low='197', close='200')
        data[-1].update(open='198', high='202', low='197', close='200', vol='80')
        result = call_product(calendar, data, {day: 'FALSE' for day in calendar}, raw_g4_reference=accepted_g4(calendar[-1], close='103', prev_close='100'))
        self.assertEqual(result['smallk_raw_base'], 'TRUE')
        self.assertEqual(result['smallk_reference']['raw_g4_prev_close'], PRODUCT.N('100'))
        self.assertEqual(result['smallk_reference']['volume_shrink'], 'TRUE')

    def test_missing_v192_state_or_raw_g4_reference_stays_unknown(self):
        calendar = d28_calendar()
        signal_date = calendar[-2]
        result = call_product(calendar, bars(calendar), {day: ('UNKNOWN' if day == signal_date else 'FALSE') for day in calendar}, raw_g4_reference=None)
        self.assertIn(signal_date, result['new_key_unknown_dates'])
        self.assertEqual(result['primary_path_redgreen'], 'UNKNOWN')
        self.assertEqual(result['smallk_raw_base'], 'UNKNOWN')
        self.assertEqual(result['baseline']['nav_smallk'], 'UNKNOWN')
        self.assertEqual(result['input_coverage']['status'], 'UNKNOWN')
        self.assertTrue(result['input_coverage']['v192_breakout_unknown_or_missing_dates'])

    def test_future_bars_are_excluded_before_any_predicate(self):
        calendar = d28_calendar() + [20261029]
        prefix = bars(calendar[:-1])
        signals = {day: 'FALSE' for day in calendar}
        signals[calendar[-1]] = 'TRUE'
        without_future = call_product(calendar, prefix, signals, asof=20261028)
        with_future = call_product(calendar, prefix + bars([calendar[-1]]), signals, asof=20261028)
        self.assertEqual(with_future['future_bars_excluded'], 1)
        self.assertEqual(with_future['groups'], without_future['groups'])
        self.assertEqual(with_future['event_dates'], without_future['event_dates'])
        self.assertNotIn(calendar[-1], with_future['event_dates']['original_v192_true'])

    def test_known_false_baseline_dominates_unknown_gates(self):
        calendar = d28_calendar()
        baseline = {'original': 'FALSE', 'nav_pullback': 'TRUE', 'nav_breakout': 'UNKNOWN'}
        result = call_product(calendar, bars(calendar), {day: 'FALSE' for day in calendar}, baseline_memberships=baseline)
        self.assertEqual(result['groups']['original']['status'], 'FALSE')
        self.assertEqual(result['groups']['nav_pullback']['status'], 'UNKNOWN')
        self.assertEqual(result['groups']['nav_breakout']['status'], 'UNKNOWN')

    def test_old_main_anchor_mismatch_is_unknown_when_group_baseline_true(self):
        calendar = d28_calendar()
        signals = {day: 'TRUE' if day == calendar[-2] else 'FALSE' for day in calendar}
        result = call_product(calendar, bars(calendar), signals, old_main_anchor_date=calendar[-3])
        self.assertEqual(result['groups']['nav_pullback']['anchor_applicability'], 'UNKNOWN')
        self.assertIn('OLD_DESCRIPTOR_AND_NEW_FILTER_ANCHOR_DIFFER', result['groups']['nav_pullback']['reasons'])

    def test_r5_plausible_terminal_d3_remains_unknown(self):
        first = date(2025, 1, 1)
        calendar = [int((first + timedelta(days=i)).strftime('%Y%m%d')) for i in range(170)]
        data = bars(calendar)
        points = {80: 100, 90: 80, 100: 140, 110: 100, 120: 130, 169: 60}
        for start, end in zip(list(points)[:-1], list(points)[1:]):
            a, b = points[start], points[end]
            for index in range(start, end + 1):
                close = PRODUCT.N(a) + PRODUCT.N(b - a) * PRODUCT.N(index - start) / PRODUCT.N(end - start)
                data[index].update(open=str(close), close=str(close), high=str(close + 1), low=str(close - 1))
        for index in list(range(101, 111)) + list(range(121, 170)):
            data[index]['vol'] = '150'
        signals = {day: 'FALSE' for day in calendar}
        result = call_product(calendar, data, signals, raw_g4_reference=None)
        self.assertEqual(result['d3_terminal_r5']['status'], 'UNKNOWN')
        self.assertEqual(result['risk_scan']['proxy_status']['D3'], 'UNKNOWN')
        self.assertEqual(result['risk']['status'], 'UNKNOWN')
        self.assertIn('D3_TERMINAL_UNCONFIRMED', result['groups']['original']['reasons'])

    def test_missing_required_fields_is_reported_unknown_without_global_price_reject(self):
        calendar = [int((date(2026, 1, 1) + timedelta(days=i)).strftime('%Y%m%d')) for i in range(70)]
        data = bars(calendar)
        data[0].update(open='-1', high='0', low='-2', close='-1')
        data[-1]['open'] = None
        signals = {day: 'FALSE' for day in calendar}
        result = call_product(calendar, data, signals, baseline_memberships={'original': 'FALSE', 'nav_pullback': 'TRUE', 'nav_breakout': 'TRUE'}, raw_g4_reference=None)
        self.assertEqual(result['status'], 'NUMERIC_PROXIES_COMPUTED')
        self.assertEqual(result['input_coverage']['status'], 'UNKNOWN')
        self.assertEqual(result['groups']['original']['status'], 'FALSE')
        self.assertEqual(result['risk']['status'], 'UNKNOWN')
        self.assertIn('open', result['input_coverage']['missing_fields'][-1]['fields'])

    def test_unqualified_source_is_unknown_and_never_defaults_true(self):
        calendar = d28_calendar()
        result = call_product(calendar, bars(calendar), {day: 'TRUE' for day in calendar}, qualification_status='UNKNOWN')
        self.assertEqual(result['status'], 'UNKNOWN_INPUT_COVERAGE')
        self.assertEqual(result['groups']['original']['status'], 'UNKNOWN')
        self.assertEqual(result['groups']['nav_smallk']['baseline'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main(verbosity=2)
