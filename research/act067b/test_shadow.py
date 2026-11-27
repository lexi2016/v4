"""Frozen acceptance regressions for the isolated ACT-067B harness."""

import csv
import os
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from charts import render_panel
from run_shadow import CHART_BARS, blind_zip, read_forward_cases, render_left_panels
from semantic_shadow import B1_RISK_CHECKS, Session, Shadow, read_json, through_sessions, validate_contract

START = date(2024, 1, 1)
INPUT_FIELDS = ('date', 'open', 'high', 'low', 'close', 'volume', 'pct_change', 'W', 'Y', 'BBI', 'J')


def fake_session(i, *, w=10, y=9, bbi=11, j=40, pct=0, volume=100):
    return Session(START+timedelta(days=i*2), 10, 11, 9, 10, volume, pct, w, y, bbi, j)


def serialized(bar):
    return dict(zip(INPUT_FIELDS, (str(bar.day), bar.open, bar.high, bar.low, bar.close, bar.volume,
                                   bar.pct, bar.w, bar.y, bar.bbi, bar.j)))


class SemanticShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = validate_contract(read_json(Path(os.environ['ACT067B_CONTRACT'])))

    def test_b1_keeps_raw_on_d_separate_from_formal_and_ages_out_after_35_sessions(self):
        shadow = Shadow(self.rules, continuous_sessions=True)
        for i in range(36):
            shadow.advance(fake_session(i))
        raw = shadow.advance(fake_session(36, j=13))
        self.assertEqual(raw['b1_raw'], 'TRUE')
        self.assertEqual(raw['b1_phase'], 'RAW_ONLY')
        self.assertEqual(raw['b1_formal'], 'FALSE')
        self.assertEqual(raw['b1_prior_raw_dates'], '')
        for i in range(37, 72):
            day = shadow.advance(fake_session(i, j=14))
            self.assertEqual(day['b1_prior_raw_dates'], str(fake_session(36).day))
            self.assertEqual(day['b1_formal'], 'UNKNOWN')
            self.assertEqual(day['b1_primary_price_diagnostic'], 'TRUE')
            self.assertEqual(day['b1_risk_missing'].split('|'), list(B1_RISK_CHECKS))
        self.assertEqual(shadow.advance(fake_session(72))['b1_formal'], 'FALSE')

    def test_unkeyed_risk_fields_cannot_promote_b1_and_m25_stays_independent(self):
        shadow = Shadow(self.rules, continuous_sessions=True)
        shadow.advance(fake_session(0, j=10))
        row = serialized(fake_session(1, j=12, volume=70))
        row.update({'b1_pullback_drawdown_pct': 8, 'b1_pullback_volume_ratio': 0.4,
                    **{f'risk_{key.lower()}': False for key in B1_RISK_CHECKS}})
        output = shadow.advance(Session.from_row(row))
        self.assertEqual(output['b1_formal'], 'UNKNOWN')
        self.assertEqual(output['m25'], 'UNKNOWN')
        for event in ('D_DAMAGE', 'T_YELLOW_TEST', 'C_REBUILD_CONFIRM', 'HISTORY_PRESERVED', 'RISK_CLEAR'):
            self.assertEqual(output[f'm25_{event}_status'], 'UNKNOWN')
            self.assertTrue(output[f'm25_{event}_missing'])

    def test_b2_exact_thresholds_use_d_in_j_window_and_exclude_d_from_volume_mean(self):
        shadow = Shadow(self.rules, continuous_sessions=True)
        for i in range(4):
            shadow.advance(fake_session(i))
        equal = shadow.advance(fake_session(4, j=13, volume=125, pct=4))
        self.assertEqual(equal['B2_1006_SCREEN'], 'TRUE')
        self.assertEqual(equal['B2_151_PREV_VOL_X1_20'], 'TRUE')
        self.assertEqual(equal['USER_FORMULA_B2_F03'], 'FALSE')
        self.assertEqual(equal['b2_f03_failed_clauses'], 'J_LT_13_WITHIN_D_MINUS_2_TO_D|VOL_GT_1_25_TIMES_PRIOR_4_MEAN|PCT_GT_4')
        candidate = shadow.advance(fake_session(5, j=12, volume=134, pct=4.001))
        self.assertEqual(candidate['USER_FORMULA_B2_F03'], 'TRUE')
        self.assertEqual(candidate['b2_f03_prior_4_mean_volume'], 106.25)
        self.assertEqual(candidate['B2_151_PREV_VOL_X1_20'], 'FALSE')
        self.assertEqual(candidate['B2_ORAL_CORE'], 'UNKNOWN')
        self.assertEqual(candidate['B2_TREND_CONFIRMATION'], 'UNKNOWN')
        self.assertEqual(candidate['USER_FORMULA_B2_F03_prior_d0_dates'], '')
        self.assertEqual(candidate['USER_FORMULA_B2_F03_formal_retest'], 'UNKNOWN')
        for i in range(6, 16):
            previous = shadow.advance(fake_session(i))
            self.assertEqual(previous['USER_FORMULA_B2_F03_prior_d0_dates'], str(fake_session(5).day))
            self.assertEqual(previous['USER_FORMULA_B2_F03_formal_retest'], 'UNKNOWN')
        expired = shadow.advance(fake_session(16))
        self.assertEqual(expired['USER_FORMULA_B2_F03_prior_d0_dates'], '')
        self.assertEqual(expired['USER_FORMULA_B2_F03_formal_retest'], 'FALSE')

    def test_b1_diagnostic_volume_windows_are_complete_prior_sessions_and_do_not_qualify(self):
        shadow = Shadow(self.rules, continuous_sessions=True)
        for i in range(10):
            shadow.advance(fake_session(i, volume=100+i))
        day = shadow.advance(fake_session(10, volume=214, j=12))
        self.assertEqual(day['b1_nonqualifying_prior_ma5_window_start'], str(fake_session(5).day))
        self.assertEqual(day['b1_nonqualifying_prior_ma5_window_end'], str(fake_session(9).day))
        self.assertEqual(day['b1_nonqualifying_prior_ma5_denominator'], 107)
        self.assertEqual(day['b1_nonqualifying_prior_ma5_d_volume_ratio'], 2)
        self.assertEqual(day['b1_nonqualifying_prior_ma10_denominator'], 104.5)
        self.assertEqual(day['b1_pullback_ma5_denominator'], 'UNKNOWN')
        self.assertEqual(day['b1_pullback_attack_peak_denominator'], 'UNKNOWN')
        self.assertEqual(day['b1_formal'], 'UNKNOWN')

    def test_b2_count_uses_exactly_three_bars_and_white_must_exceed_yellow(self):
        shadow = Shadow(self.rules, continuous_sessions=True)
        for i in range(6):
            shadow.advance(fake_session(i, j=12 if i == 3 else 40))
        output = shadow.advance(fake_session(6, w=9, y=9, pct=5, volume=150))
        self.assertEqual(output['USER_FORMULA_B2_F03'], 'FALSE')
        self.assertEqual(output['b2_f03_failed_clauses'], 'J_LT_13_WITHIN_D_MINUS_2_TO_D|W_GT_Y')

    def test_future_append_never_changes_engine_or_png_or_zip(self):
        d = fake_session(CHART_BARS-1).day
        selected = [{'date': str(d), 'chart_id': 'A01'}]
        with TemporaryDirectory(dir=os.environ.get('ACT067B_TEST_TMPDIR')) as tmp:
            folder = Path(tmp)
            baseline = folder/'baseline.csv'
            with baseline.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, INPUT_FIELDS)
                writer.writeheader()
                writer.writerows(serialized(fake_session(i)) for i in range(CHART_BARS))
            extended = folder/'extended.csv'
            # A future date that is not even parseable proves through_sessions never requests that row.
            extended.write_bytes(baseline.read_bytes()+b'ILLEGAL_FUTURE_ROW\n')
            shadow_left = Shadow(self.rules, continuous_sessions=True)
            shadow_right = Shadow(self.rules, continuous_sessions=True)
            self.assertEqual([shadow_left.advance(s) for s in through_sessions(baseline, d)],
                             [shadow_right.advance(s) for s in through_sessions(extended, d)])
            first_zip, second_zip = folder/'first.zip', folder/'second.zip'
            blind_zip(first_zip, render_left_panels(baseline, selected))
            blind_zip(second_zip, render_left_panels(extended, selected))
            self.assertEqual(first_zip.read_bytes(), second_zip.read_bytes())
            with ZipFile(first_zip) as archive:
                self.assertEqual(sorted(archive.namelist()), ['A01.png', 'manifest.json'])
                manifest = archive.read('manifest.json')
                self.assertNotIn(str(d).encode(), manifest)
                self.assertNotIn(b'D+15', manifest)
                self.assertNotIn(b'002865', manifest)

    def test_atlas_requires_exact_forward_offsets_and_path_uses_no_d_candle(self):
        anchor = fake_session(0)
        selection = [{'date': str(anchor.day), 'chart_id': 'A01', 'td_idx': 50}]
        with TemporaryDirectory(dir=os.environ.get('ACT067B_TEST_TMPDIR')) as tmp:
            path = Path(tmp)/'future.csv'
            with path.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, ('anchor_D', 'offset', 'td_idx', *INPUT_FIELDS))
                writer.writeheader()
                for i in range(1, 16):
                    writer.writerow({'anchor_D': anchor.day, 'offset': i, 'td_idx': 50+i, **serialized(fake_session(i))})
            bars = read_forward_cases(path, selection)[str(anchor.day)]
            self.assertEqual((bars[0].day, bars[-1].day), (fake_session(1).day, fake_session(15).day))
            self.assertEqual(len(bars), 15)
            updated = [*bars[:-1], replace(bars[-1], high=20, close=19)]
            self.assertNotEqual(render_panel(bars, forward_reference_close=anchor.close),
                                render_panel(updated, forward_reference_close=anchor.close))
            with self.assertRaises(ValueError):
                render_panel([anchor, *bars], forward_reference_close=anchor.close)
            path.write_text(path.read_text().replace(str(fake_session(1).day), str(anchor.day), 1))
            with self.assertRaises(ValueError):
                read_forward_cases(path, selection)


if __name__ == '__main__':
    unittest.main()
