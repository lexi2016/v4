"""Bounded regression: accepted source close projection, never observation data."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from infrastructure.research_workbench_quote_reference import SourceCloseReferences, FLAGS
from infrastructure.research_workbench_host import ResearchWorkbenchHost


class QuoteReferencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.snapshot = self.root / 'adjustment_input_snapshot.json'
        self.snapshot.write_text('{}')
        self.snapshot_ref = dict(path=str(self.snapshot), sha256=hashlib.sha256(b'{}').hexdigest())
        self.basis = dict(price_basis='QFQ_ASOF', amount_basis='RAW_TURNOVER', volume_basis='QFQ_EVENT_VOLUME', asof_date=20261105)
        contract = dict(generation_id='g', input_sha256='i', asof_date=20261105,
                        snapshot_file_sha256=self.snapshot_ref['sha256'], market_basis={'A': self.basis})
        self.selector = self.root / 'selector.parquet'
        table = pa.Table.from_pylist([
            dict(ts_code='000410.SZ', trade_date='20261105', close=5.46, pct_chg=0.1834862385, amount=529314656.0),
            dict(ts_code='603007.SH', trade_date='20261105', close=None, pct_chg=None, amount=None),
            dict(ts_code='920007.BJ', trade_date='20261104', close=39.49, pct_chg=29.9, amount=101527840.0),
        ]).replace_schema_metadata({b'a_share_qfq_contract_v1': json.dumps(contract).encode()})
        pq.write_table(table, self.selector)
        self.digest = hashlib.sha256(self.selector.read_bytes()).hexdigest()
        self.stage = dict(status='READY', selector_pointer_ready=True, selector=str(self.selector),
                          candidates={'selector': str(self.selector)}, candidate_sha256={'selector': self.digest},
                          target_date=20261105, **contract, **FLAGS)
        self.stage_path = self.root / 'stage_status.json'
        self.save_stage()
        self.product = dict(data_date='20261105', source_generation='g', manifest={'sha256':'m'},
                            source_identity=dict(generation='g', asof=20261105, input_sha256='i', basis=self.basis,
                                                 snapshot=self.snapshot_ref, selector_artifact_sha256=self.digest),
                            processed_count=5808, artifact={}, rows=[dict(symbol=s, groups='original') for s in ['000410.SZ','603007.SH','920007.BJ']])

    def save_stage(self):
        self.stage_path.write_text(json.dumps(self.stage))

    def test_exact_date_scope_null_and_cached_single_read(self):
        reader = SourceCloseReferences()
        with patch('pyarrow.parquet.read_table', wraps=pq.read_table) as read:
            first = reader.read(self.product)
            second = reader.read(self.product)
            self.assertEqual(read.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first['scope_count'], 3)
        self.assertEqual(first['available_count'], 2)
        self.assertEqual(first['rows']['000410.SZ']['price'], 5.46)
        self.assertIsNone(first['rows']['603007.SH']['price'])
        self.assertNotIn('920007.BJ', first['rows'])
        self.assertIsNone(first['source_asof'])
        self.assertNotIn('observation_date', first)
        self.assertNotIn('target_return', first)
        first['rows']['000410.SZ']['price'] = 0
        self.assertEqual(reader.read(self.product)['rows']['000410.SZ']['price'], 5.46)

    def test_identity_conflicts_fail_closed(self):
        for key, value in [('generation_id','other'), ('input_sha256','other'), ('target_date',20261104),
                           ('snapshot_file_sha256','f'*64), ('status','PARTIAL'), ('production_allowed',True)]:
            with self.subTest(key=key):
                stage = copy.deepcopy(self.stage); stage[key] = value
                self.stage_path.write_text(json.dumps(stage))
                with self.assertRaises(ValueError): SourceCloseReferences().read(self.product)
        self.save_stage()
        for key, value in [('generation','other'), ('asof',20261104), ('selector_artifact_sha256','f'*64)]:
            p = copy.deepcopy(self.product); p['source_identity'][key] = value
            with self.subTest(product=key), self.assertRaises(ValueError): SourceCloseReferences().read(p)

    def test_source_drift_invalidates_cache_and_no_cross_day_reuse(self):
        reader = SourceCloseReferences(); reader.read(self.product)
        with self.selector.open('ab') as stream: stream.write(b'drift')
        with self.assertRaisesRegex(ValueError, 'SHA_DRIFT'): reader.read(self.product)
        p = copy.deepcopy(self.product); p['data_date'] = '20261106'
        with self.assertRaises(ValueError): reader.read(p)

    def test_day_adds_reference_without_changing_scope_groups_or_history(self):
        h = ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
        h._view = lambda *args: self.product
        h._observation_date = lambda *args: '2026-11-06'
        h._is_skill_date = lambda *args: False
        h._module_reference = lambda *args: None
        h.workflow = lambda *args: {'time_contract':{'nodes':[]}}
        h._lock = threading.RLock(); h._row_cache = {}; h._statistics_cache = {}
        h.classifications = SimpleNamespace(root=None)
        h.binding = {}; h._quote_references = SourceCloseReferences()
        before = copy.deepcopy(self.product)
        day = h.day('2026-11-05')
        self.assertEqual(day['scope_count'], 3)
        self.assertEqual(day['observation_date'], '2026-11-06')
        self.assertEqual(day['source_close_reference']['rows']['000410.SZ']['price'], 5.46)
        self.assertTrue(all(r['group_states']['original']=='TRUE' for r in day['rows']))
        self.assertEqual(self.product, before)
        self.assertEqual(day['statistics_status'], 'CANNOT_CONFIRM_PROJECTION_MISSING')
        self.stage_path.unlink()
        failed = h.day('2026-11-05')
        self.assertTrue(failed['source_close_reference']['status'].startswith('CANNOT_CONFIRM'))
        self.assertEqual(failed['scope_count'], 3)


if __name__ == '__main__': unittest.main()
