"""Synthetic consumer contract tests: never load weights or production data."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

import screen as s


class ConsumerContractTests(unittest.TestCase):
    def setUp(self):
        self.order = json.loads(s.ORDER.read_text())
        self.codes = [f'{i:06d}.SH' for i in range(1, 5807)] + ['000001.SZ', '430001.BJ']
        self.coverage = pd.DataFrame({'ts_code': self.codes, 'signal_date': s.ASOF,
                                      'input_status': 'NO_D05_BAR', 'gap_reason': 'SYNTHETIC_NO_BAR'})
        selected = self.codes[:13] + self.codes[-2:]
        self.coverage.loc[self.coverage.ts_code.isin(selected), ['input_status', 'gap_reason']] = ['BOUND', '']
        self.features = pd.DataFrame({'ts_code': selected, 'signal_date': s.ASOF})
        for field in self.order:
            self.features[field] = np.nan if field in s.masked_features(self.order) else 1.0
        self.features['target_domain'] = pd.Series([True] * 13 + [False, None], dtype=object)
        self.features['domain_reason'] = 'SYNTHETIC_ORIGINAL_RULE_EVIDENCE'

    def validate(self):
        return s.validate_frames(self.features, self.coverage, self.order)

    def test_three_markets_and_original_unknown_masks_are_accepted(self):
        bound = self.validate()
        self.assertEqual(set(bound.ts_code.str[-2:]), {'SH', 'SZ', 'BJ'})
        self.assertEqual(len(bound), 15)

    def test_unmasked_missing_is_rejected_before_predict(self):
        self.features.loc[0, 'J'] = np.nan
        with self.assertRaisesRegex(ValueError, 'UNBOUND_UNMASKED'):
            self.validate()

    def test_fake_frozen_zero_is_rejected(self):
        field = next(iter(s.masked_features(self.order)))
        self.features.loc[0, field] = 0.0
        with self.assertRaisesRegex(ValueError, 'FROZEN_MASK_CONFLICT'):
            self.validate()

    def test_feature_reordering_and_duplicate_keys_are_rejected(self):
        first, second = self.order[:2]
        columns = self.features.columns.tolist()
        a, b = columns.index(first), columns.index(second)
        columns[a], columns[b] = columns[b], columns[a]
        self.features = self.features[columns]
        with self.assertRaisesRegex(ValueError, 'FEATURE_COLUMN_ORDER'):
            self.validate()
        self.features = pd.concat([self.features, self.features.iloc[:1]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_CODE'):
            self.validate()

    def test_wrong_date_and_incomplete_universe_are_rejected(self):
        self.features.loc[0, 'signal_date'] -= 1
        with self.assertRaisesRegex(ValueError, 'DATE_CONFLICT'):
            self.validate()
        self.features.loc[0, 'signal_date'] = s.ASOF
        self.coverage = self.coverage.iloc[:-1]
        with self.assertRaisesRegex(ValueError, '5808'):
            self.validate()

    def test_integer_and_text_domain_do_not_enter_true_gate(self):
        for invalid in (1, 'True', 'FALSE'):
            self.features.loc[0, 'target_domain'] = invalid
            with self.assertRaisesRegex(ValueError, 'DOMAIN_MUST_BE_BOOLEAN'):
                self.validate()

    def test_unavailable_requires_reason_and_bound_requires_row(self):
        self.coverage.loc[30, 'gap_reason'] = ''
        with self.assertRaisesRegex(ValueError, 'UNAVAILABLE_WITHOUT_REASON'):
            self.validate()
        self.coverage.loc[30, ['input_status', 'gap_reason']] = ['BOUND', '']
        with self.assertRaisesRegex(ValueError, 'BOUND_CODE_WITHOUT_FEATURE_ROW'):
            self.validate()

    def test_top10_ties_domain_gate_and_full_readback_without_second_predict(self):
        bound = self.validate().sample(frac=1, random_state=42)

        class Predictor:
            calls = 0

            def predict(inner, frame):
                inner.calls += 1
                # Outside/UNKNOWN outrank TRUE rows but cannot enter main list.
                return np.where(frame.target_domain.eq(True), 0.25, 999.0)

        model = Predictor()
        result = s.predict_and_rank(model, bound, self.coverage)
        expected = sorted(self.features.loc[self.features.target_domain.eq(True), 'ts_code'])[:10]
        self.assertEqual(result.loc[result.primary_observation, 'ts_code'].tolist(), expected)
        self.assertEqual(len(result), 5808)
        self.assertEqual(result.selection_status.value_counts()['DOMAIN_UNKNOWN'], 1)
        self.assertTrue(result[['d_plus_1_return_pct', 't5_return_pct']].isna().all().all())
        s.OUT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='consumer_test_', dir=s.OUT) as temp:
            top = s.save_and_verify(result, Path(temp))
            self.assertEqual(top.ts_code.tolist(), expected)
        self.assertEqual(model.calls, 1)

    def test_small_domain_is_not_padded(self):
        self.features['target_domain'] = False
        self.features.loc[:1, 'target_domain'] = True

        class Predictor:
            def predict(self, frame):
                return np.arange(len(frame), dtype=float)

        result = s.predict_and_rank(Predictor(), self.validate(), self.coverage)
        self.assertEqual(result.primary_observation.sum(), 2)

    def test_small_seventeen_digit_score_csv_round_trip(self):
        score = 0.00012345678901234567

        class Predictor:
            def predict(self, frame):
                return np.full(len(frame), score)

        result = s.predict_and_rank(Predictor(), self.validate(), self.coverage)
        s.OUT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='consumer_test_', dir=s.OUT) as temp:
            top = s.save_and_verify(result, Path(temp))
            self.assertEqual(len(top), 10)
            for filename in ('ALL_CODES_RANKED.csv', 'PRIMARY_OBSERVATIONS.csv'):
                restored = pd.read_csv(Path(temp) / filename, float_precision='round_trip')
                self.assertTrue(restored.score_uncalibrated.dropna().eq(score).all())

    def test_prediction_nan_is_rejected(self):
        class Predictor:
            def predict(self, frame):
                return np.full(len(frame), np.nan)

        with self.assertRaisesRegex(ValueError, 'INVALID_MODEL_PREDICTION'):
            s.predict_and_rank(Predictor(), self.validate(), self.coverage)

    def test_date_identity_binding_is_checked_before_reading_files(self):
        binding = {'signal_date': 20261104, 'source_generation': s.GENERATION}
        with self.assertRaisesRegex(ValueError, 'SOURCE_DATE_OR_GENERATION'):
            s.validate_binding(binding, self.order)

    def test_explicit_column_mapping_preserves_values_and_rejects_ambiguity(self):
        original = pd.DataFrame({'old_code': ['000001.SZ'], 'old_J': [12.5], 'unrelated': [999]})
        mapped = s.map_columns(original, {'ts_code': 'old_code', 'J': 'old_J'})
        self.assertEqual(mapped.to_dict('records'), [{'ts_code': '000001.SZ', 'J': 12.5}])
        self.assertEqual(original.old_J.iloc[0], 12.5)
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS_COLUMN_MAP'):
            s.map_columns(original, {'J': 'old_J', 'other': 'old_J'})

    def test_per_code_input_identity_keeps_unknown_rows_and_original_feature_row(self):
        class Predictor:
            def predict(self, frame):
                return np.arange(len(frame), dtype=float)

        result = s.predict_and_rank(Predictor(), self.validate(), self.coverage)
        identity = {'features': {'path': '/synthetic/not_real', 'sha256': 'synthetic'}, 'coverage': {'sha256': 'synthetic_coverage'}}
        enriched = s.add_feature_identity(result, self.features, identity, self.order)
        self.assertEqual(enriched.ts_code.tolist(), result.ts_code.tolist())
        self.assertEqual(enriched.feature_row_present.sum(), 15)
        self.assertEqual(enriched.loc[enriched.ts_code.eq(self.features.ts_code.iloc[0]), 'feature_input_row'].iloc[0], 0)
        self.assertTrue(enriched.loc[enriched.feature_row_present, 'observed_unmasked_feature_count'].eq(63).all())
        self.assertTrue(enriched.loc[enriched.feature_row_present, 'frozen_unknown_feature_count'].eq(24).all())
        s.OUT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='consumer_test_', dir=s.OUT) as temp:
            s.save_and_verify(enriched, Path(temp))


if __name__ == '__main__':
    unittest.main(verbosity=2)
