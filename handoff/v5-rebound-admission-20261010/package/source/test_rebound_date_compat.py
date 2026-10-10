"""SYNTHETIC schema regression; real private assets are tested separately."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from v5_shadow import rebound_panel_repair as repair
from test_rebound_panel_repair import SyntheticRepairFixture

class DateStorageCompatibility(unittest.TestCase):
    def test_integer_parent_raw_publish_preserves_date_dtype_and_old_values(self):
        with tempfile.TemporaryDirectory() as directory:
            fx = SyntheticRepairFixture(Path(directory).resolve())
            parent = fx.frame.copy()
            parent['trade_date'] = parent.trade_date_compact.astype('int64')
            fx.bind_parent(parent)
            fx.bind_synthetic_raw_fetch_record()
            before = (fx.asset / fx.panel_relative).read_bytes()
            with patch.object(repair, '_verify_owner', return_value=None):
                try:
                    result = fx.publish()
                except Exception as error:
                    self.fail(f'Integer-date parent must publish losslessly: {type(error).__name__}: {error}')
                child = json.loads((fx.asset / result['manifest_relative']).read_bytes())
                frame = pd.read_parquet(fx.asset / child['panel_relative'])
                self.assertEqual(frame.trade_date.dtype, parent.trade_date.dtype)
                pd.testing.assert_frame_equal(frame.iloc[:len(parent)][parent.columns].reset_index(drop=True), parent, check_dtype=False, check_exact=True)
                self.assertEqual(frame.trade_date.iloc[len(parent):].tolist(), [20260929, 20261005])
                self.assertEqual(fx.witness(result)['panel_rows'], len(parent) + 2)
                self.assertTrue(fx.publish()['reused'])
            self.assertEqual((fx.asset / fx.panel_relative).read_bytes(), before)

    def test_string_parent_and_integer_widths_keep_exact_storage(self):
        for dtype in ('int32', 'int64', 'uint32', 'Int64', 'object', 'string'):
            with self.subTest(dtype=dtype):
                tokens = ['20260928', '20261008']
                values = tokens if dtype in ('object', 'string') else [20260928, 20261008]
                parent = pd.DataFrame({'trade_date': pd.Series(values, dtype=dtype), 'trade_date_compact': tokens})
                addition = pd.DataFrame({'trade_date': ['20261005'], 'trade_date_compact': ['20261005'], 'trade': [45276.0]})
                before = parent.copy(deep=True); raw = addition.copy(deep=True)
                result = repair._align_repair_trade_dates(parent, addition)
                self.assertEqual(result.trade_date.dtype, parent.trade_date.dtype)
                self.assertEqual(result.trade_date.tolist(), ['20261005'] if dtype in ('object', 'string') else [20261005])
                self.assertEqual(result.trade.tolist(), [45276.0])
                pd.testing.assert_frame_equal(parent, before)
                pd.testing.assert_frame_equal(addition, raw)

    def test_invalid_or_ambiguous_addition_dates_rejected(self):
        parent = pd.DataFrame({'trade_date': pd.Series([20261008],dtype='int64'), 'trade_date_compact':['20261008']})
        bad = [None, True, 20261005.0, 20261005.5, '2026-10-05', '2026105', '20261005 ', '+20261005', '２０２６１００５', '20260230', '20261301', '20261006']
        for value in bad:
            with self.subTest(value=repr(value)):
                addition = pd.DataFrame({'trade_date':pd.Series([value],dtype='object'), 'trade_date_compact':['20261005']})
                with self.assertRaisesRegex(ValueError, 'REPAIR_DATE_STORAGE'):
                    repair._align_repair_trade_dates(parent, addition)

    def test_parent_float_null_mixed_and_mismatched_dates_rejected(self):
        addition = pd.DataFrame({'trade_date':['20261005'], 'trade_date_compact':['20261005']})
        for values, compact in [([20261008.0],['20261008']),([None],['20261008']),([20261008,'20261007'],['20261008','20261007']),(['20260230'],['20260230']),([20261007],['20261008']),([True],['20261008'])]:
            with self.subTest(values=values):
                parent = pd.DataFrame({'trade_date':values,'trade_date_compact':compact})
                with self.assertRaisesRegex(ValueError, 'REPAIR_DATE_STORAGE'):
                    repair._align_repair_trade_dates(parent, addition)

    def test_no_parent_date_column_keeps_legacy_fixture_contract(self):
        parent = pd.DataFrame({'trade_date_compact':['20261008']})
        addition = pd.DataFrame({'trade_date':['20261005'],'trade_date_compact':['20261005']})
        pd.testing.assert_frame_equal(repair._align_repair_trade_dates(parent,addition),addition)
