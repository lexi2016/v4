"""Pure synthetic regression for rankable truth and the frozen report oracle."""
from copy import deepcopy
import unittest

import long_report_recovery194 as recovery
import report194


class RecoveryTests(unittest.TestCase):
    def fixture(self):
        dates = [f'2024-01-{day:02d}' for day in range(2, 12)]
        truth = [{'target_date': day, 'code': code, 'label': int(code == 'a')}
                 for day in dates for code in ('a', 'b', 'c')]
        calendar = {day: {'target_date': day, 'truth_rankable_research_rows': '3',
                         'truth_positive_denominator': '1'} for day in dates}
        universe = {'a', 'b', 'c', 'unrankable_1', 'unrankable_2'}
        return dates, truth, calendar, universe

    def test_rankable_daily_subset_is_valid_without_filling_unknown_labels(self):
        dates, truth, calendar, universe = self.fixture()
        selected = {day: {'a', 'b'} for day in dates}
        # Synthetic Top100 denominator is min(100, actual rankable rows).
        for row in truth:
            row['label'] = 1
        for row in calendar.values():
            row['truth_positive_denominator'] = '3'
        projected, positive, audit = recovery.collect_truth(truth, dates, calendar, universe, selected)
        self.assertEqual(len(projected), len(truth))
        self.assertTrue(all(row['unknown_or_unrankable_research_codes'] == 2 for row in audit['daily']))
        self.assertFalse(any(row['code'].startswith('unrankable') for row in projected))

    def test_calendar_count_drift_pool_violation_duplicate_and_missing_selected_rejected(self):
        dates, truth, calendar, universe = self.fixture()
        for row in truth:
            row['label'] = 1
        for row in calendar.values():
            row['truth_positive_denominator'] = '3'
        changed = deepcopy(calendar)
        changed[dates[0]]['truth_rankable_research_rows'] = '4'
        with self.assertRaisesRegex(ValueError, 'RANKABLE_ROW_COUNT_DRIFT'):
            recovery.collect_truth(truth, dates, changed, universe, {})
        wrong = deepcopy(truth)
        wrong[0]['code'] = 'OUTSIDE'
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_FROZEN_UNIVERSE'):
            recovery.collect_truth(wrong, dates, calendar, universe, {})
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_OOF_TRUTH_KEY'):
            recovery.collect_truth([truth[0], *truth], dates, calendar, universe, {})
        with self.assertRaisesRegex(ValueError, 'SELECTED_KEY_MISSING_TRUTH'):
            recovery.collect_truth(truth, dates, calendar, universe, {dates[0]: {'unrankable_1'}})

    def test_oracle_projection_preserves_full_oracle_metrics_and_bootstrap(self):
        dates = [f'2024-01-{day:02d}' for day in range(2, 12)]
        # >100 rankable names permits true unselected negatives in this fixture.
        universe = {f'{i:03d}' for i in range(130)}
        truth = [{'target_date': day, 'code': f'{i:03d}', 'label': int(i < 100)}
                 for day in dates for i in range(120)]
        calendar = {day: {'target_date': day, 'truth_rankable_research_rows': '120',
                         'truth_positive_denominator': '100'} for day in dates}
        baseline = [{'target_date': day, 'code': '100', 'score': 0.7} for day in dates]
        candidate = [{'target_date': day, 'code': '000' if i % 2 else '101', 'score': 0.8}
                     for i, day in enumerate(dates)]
        selected = {day: {'100', candidate[i]['code']} for i, day in enumerate(dates)}
        projected, _, audit = recovery.collect_truth(truth, dates, calendar, universe, selected)
        expected = report194.evaluate(dates, baseline, candidate, truth, list(calendar.values()))
        actual = report194.evaluate(dates, baseline, candidate, projected, list(calendar.values()))
        self.assertEqual(actual, expected)
        self.assertLess(len(projected), len(truth))
        self.assertEqual(audit['all_truth_rows_streamed'], 1200)

    def test_daily_comparison_preserves_natural_counts_and_pairwise_membership(self):
        dates = ['2024-01-02']
        positive = {dates[0]: {'a'}}
        raw = {dates[0]: {'a', 'b', 'c'}}
        baseline = {dates[0]: {'a', 'b'}}
        candidate = {dates[0]: {'a', 'c'}}
        calendar = {dates[0]: {'truth_positive_denominator': '1'}}
        audit = {'fold_01': {'any_source_state_variation_seen': False, 'all_source_lanes_unknown': True}}
        daily, flags = recovery.selection_comparison(dates, positive, raw, baseline, candidate,
                                                     calendar, {dates[0]: 'fold_01'}, audit)
        self.assertEqual(daily[0]['raw_formula255_selected'], 3)
        self.assertEqual(daily[0]['technical11_l2_vs_v194_common'], 1)
        self.assertEqual(daily[0]['technical11_l2_vs_v194_new'], 1)
        self.assertEqual(daily[0]['technical11_l2_vs_v194_lost'], 1)
        self.assertEqual(daily[0]['technical11_l2_vs_v194_common_hits'], 1)
        self.assertEqual(len(flags), 1)


if __name__ == '__main__':
    unittest.main()
