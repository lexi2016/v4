"""Frozen mapper checks: source mismatch rejects, absent stages stay absent."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ops.build_a_share_pool_top200 import canonical_symbol, project_date


class FrozenDetailsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage = self.root / 'stage.csv'
        self.stage.write_text('code\nSH.600001\n')
        self.top = self.root / 'top.json'
        self.top.write_text(json.dumps(dict(data_date='20261104', top200=[dict(rank=1, symbol='600001.SH', name='测试甲', change_pct=10.0), dict(rank=2, symbol='000001.SZ', name='测试乙', change_pct=5.0)])))
        self.ref = dict(path=str(self.top), sha256=self.sha(self.top))
        self.entry = dict(date='20261104', a_pool=dict(selected_count=1, hit_count=1, api_input_fingerprint='frozen', pools=[dict(pool_id='a_d1_premarket_pool', materialized=True, selected_count=1, hit_count=1, source_sha256='pool-sha')]), top200=dict(source='STORED_TOP200_ARTIFACT', source_sha256=self.ref['sha256'], top_count=2, min_change_pct=5.0), seven_stage=dict(selected_count=1, hit_count=1, stages={'STAGE_0930_0935': dict(status='READY', row_count=1, unique_codes=1, hit_count=1, artifact_relative='stage.csv', artifact_sha256=self.sha(self.stage)), 'STAGE_0925': dict(status='NOT_MATERIALIZED', hit_count=None)}))
        self.pages = [dict(trade_date='20261104', input_fingerprint='frozen', a_all_pool_rows=[dict(symbol='A.600001')], pools=[dict(pool_id='a_d1_premarket_pool', source_sha256='pool-sha', rows=[dict(symbol='A.600001')])])]

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_maps_frozen_rows_without_using_later_stages(self):
        (self.root / 'later-0925.csv').write_text('code\nSZ.000001\n')
        result = project_date(self.entry, self.ref, self.pages, self.root)
        self.assertEqual(result['detail_evidence']['counts'], dict(rows=2, pool_hits=1, stage_hits=1))
        self.assertEqual(result['stocks'][0]['stage_memberships'], ['STAGE_0930_0935'])
        self.assertEqual(result['stocks'][1]['stage_memberships'], [])
        self.assertEqual(result['seven_stage'], self.entry['seven_stage'])
        self.assertNotIn('stocks', self.entry)

    def test_rejects_drifted_pool_fingerprint_and_source(self):
        for field in ['input_fingerprint', 'source_sha256']:
            pages = copy.deepcopy(self.pages)
            target = pages[0] if field == 'input_fingerprint' else pages[0]['pools'][0]
            target[field] = 'changed'
            with self.assertRaisesRegex(ValueError, 'MISMATCH'):
                project_date(self.entry, self.ref, pages, self.root)

    def test_rejects_drifted_top_and_stage_bytes(self):
        for path in [self.top, self.stage]:
            old = path.read_bytes()
            path.write_bytes(old + b'\n')
            with self.assertRaisesRegex(ValueError, 'SHA_MISMATCH'):
                project_date(self.entry, self.ref, self.pages, self.root)
            path.write_bytes(old)

    def test_normalizes_existing_symbol_forms(self):
        self.assertEqual(canonical_symbol('SH.600001'), '600001.SH')
        self.assertEqual(canonical_symbol('A.000001'), '000001.SZ')
        self.assertEqual(canonical_symbol('920001.BJ'), '920001.BJ')
        self.assertIsNone(canonical_symbol('HK.00700'))

    def test_delivered_rows_reconcile_all_frozen_aggregate_counts(self):
        path = Path(__file__).resolve().parents[1] / 'apps/web/public/top200-hit.json'
        doc = json.loads(path.read_bytes())
        for entry in doc['dates']:
            if entry.get('detail_status') != 'SAME_SNAPSHOT_RECONCILED':
                continue
            rows = entry['stocks']
            self.assertEqual(len(rows), entry['top200']['top_count'])
            self.assertEqual([r['rank'] for r in rows], list(range(1, len(rows) + 1)))
            self.assertEqual(sum(r['pool_hit'] for r in rows), entry['a_pool']['hit_count'])
            self.assertEqual(sum(bool(r['stage_memberships']) for r in rows), entry['seven_stage']['hit_count'])
            for pool in entry['a_pool']['pools']:
                if pool['materialized']:
                    self.assertEqual(sum(pool['pool_id'] in r['pool_memberships'] for r in rows), pool['hit_count'])


if __name__ == '__main__':
    unittest.main()
