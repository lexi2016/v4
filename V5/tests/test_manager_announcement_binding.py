"""Next-candidate regressions; original 758-file announcement package on Mac.

This test-only candidate does not change bb61f2e's production code or source
capsules. Set the existing V5_ANNOUNCEMENT_REQUEST_PATH; never collect inputs.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from v5_shadow.manager_plan import _snapshot, run_manager_plan
from v5_shadow.digests import canonical_bytes, MAX_JSON_BYTES

MIB = 1024 * 1024
RUN = 'a' * 32


class ManagerAnnouncementLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v5-manager-size-regression-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def binding(self, sizes):
        files = {}
        for relative, size in sizes.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            # Valid JSON with trailing whitespace; exercise byte admission,
            # without inventing a valid business product or mocking an owner.
            digest = hashlib.sha256()
            with path.open('wb') as stream:
                stream.write(b'0');digest.update(b'0');remaining = size - 1
                while remaining:
                    block = b' ' * min(remaining, MIB)
                    stream.write(block);digest.update(block);remaining -= len(block)
            files[relative] = digest.hexdigest()
        return dict(root=str(self.root), files=files)

    def test_exact_corpus_path_accepts_observed_real_size_without_truncation(self):
        relative = f'announcement_agent_runs/{RUN}/evidence/body_corpus.json'
        binding = self.binding({relative: 21861605})
        snapshot = _snapshot(binding)
        self.assertEqual(len(snapshot[relative]), 21861605)
        self.assertEqual(hashlib.sha256(snapshot[relative]).hexdigest(), binding['files'][relative])
        self.assertEqual(MAX_JSON_BYTES, 16 * MIB)

    def test_non_corpus_files_keep_sixteen_mib_limit(self):
        paths = [f'announcement_agent_runs/{RUN}/evidence/reader_output.json',
                 f'announcement_agent_runs/{RUN}/evidence/body_corpus.json.extra',
                 'announcement_agent_runs/not-a-run/evidence/body_corpus.json',
                 'workspace_announcements/20261008/eastmoney_date_catalog/20261007/analysis.v1.json']
        for relative in paths:
            with self.subTest(relative=relative):
                binding = self.binding({relative: 16 * MIB + 1})
                with self.assertRaises(ValueError):
                    _snapshot(binding)

    def test_announcement_group_keeps_sixty_four_mib_limit(self):
        binding = self.binding({
            f'announcement_agent_runs/{RUN}/evidence/body_corpus.json': 32 * MIB,
            f'announcement_agent_runs/{RUN}/evidence/reviewer_output.json': 16 * MIB,
            f'announcement_agent_runs/{RUN}/evidence/analysis_product.json': 16 * MIB,
            f'announcement_agent_runs/{RUN}/evidence/reader_output.json': 1})
        with self.assertRaises(ValueError):
            _snapshot(binding)


class ManagerAnnouncementRealOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('V5_ANNOUNCEMENT_REQUEST_PATH')
        if not path:
            raise RuntimeError('V5_ANNOUNCEMENT_REQUEST_PATH_REQUIRED_NO_SKIP')
        cls.announcement = json.loads(Path(path).read_bytes())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v5-manager-announcement-regression-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        us = self.root/'us';us.mkdir()
        output = self.root/'plans';output.mkdir()
        (output/'.v5-manager-plan-root').write_text('v5.manager-plan-root.v1\n')
        a = self.announcement
        self.assertEqual(a['target_date'], '20261008')
        self.assertEqual(a['publication_date'].replace('-', ''), '20261007')
        self.request = dict(target_date='20261008', now=datetime.now(timezone.utc).isoformat(),
            action='read', view='dynamic', selection_date=None, announcement_date='20261007',
            inputs=dict(manager=dict(root=a['manager_root'], files=copy.deepcopy(a['manager_files'])),
                        materials=dict(root=a['materials_root'], files=copy.deepcopy(a['material_files'])),
                        us=dict(root=str(us), files={})), rebound=None, manager_output_root=str(output))
        self.output = output

    def input_hashes(self):
        return {group: {name: hashlib.sha256((Path(binding['root'])/name).read_bytes()).hexdigest()
                       for name in binding['files']}
                for group,binding in self.request['inputs'].items()}

    def reviewed_pair(self, payload):
        products = payload['announcement_reviewed_analysis']['products']
        matching = [p for p in products if p['target_trade_date']=='20261008'
                    and p['publication_date']=='2026-10-07']
        self.assertEqual(len(matching), 1, products)
        item = matching[0]
        self.assertEqual(item['validation_status'], 'VERIFIED', item)
        self.assertEqual(item['status'], 'CONSUMED', item)
        self.assertTrue(item['consumed'])
        self.assertEqual(item['cutoff_status'], 'SATISFIED')
        self.assertEqual((item['selected_stock_count'], item['conditional_watch_count'],
                          item['not_assessed_stock_count']), (33,54,75))
        self.assertIn(item['product_sha256'], payload['announcement_reviewed_analysis']['consumed_product_sha256s'])
        return item

    def test_real_expanded_package_survives_snapshot_and_copy_and_original_consumption(self):
        a = self.announcement
        self.assertEqual(len(a['manager_files']), 694)
        self.assertEqual(len(a['material_files']), 64)
        self.assertEqual(sum(name.startswith('announcement_agent_runs/') for name in a['manager_files']), 624)
        corpus = [name for name in a['manager_files'] if name.endswith('/evidence/body_corpus.json')]
        self.assertEqual(len(corpus), 1)
        self.assertEqual((Path(a['manager_root'])/corpus[0]).stat().st_size, 21861605)
        before = self.input_hashes()
        result = run_manager_plan(self.request)
        self.reviewed_pair(result['payload'])
        self.assertEqual(result['payload']['date_bindings'], dict(
            selection_date='20261008', announcement_date='20261007', plan_date='20261008'))
        self.assertEqual(self.input_hashes(), before)
        self.assertEqual([p.name for p in self.output.iterdir()], ['.v5-manager-plan-root'])
        self.assertLessEqual(len(canonical_bytes(result)), 16 * MIB)
        self.assertFalse(result['natural_verified'])

    def test_real_recovery_plan_preserves_consumed_identity_and_same_run_attempt(self):
        self.request.update(action='refresh', announcement_date=None)
        result = run_manager_plan(self.request)
        item = self.reviewed_pair(result['payload'])
        self.assertEqual(result['readback']['status'], 'MATCHED')
        run = result['readback']['run_id']
        saved = json.loads((self.output/result['readback']['store_relative']/'workspace_plans/20261008'/f'{run}.json').read_bytes())
        self.assertEqual(result['readback']['attempt']['run_id'], run)
        self.assertEqual(saved['execution_kind'], 'MANUAL_REFRESH')
        self.assertEqual(self.reviewed_pair(saved['workspace'])['product_sha256'], item['product_sha256'])
        self.request['action'] = 'read'
        reread = run_manager_plan(self.request)
        self.assertEqual(reread['payload']['plan_product']['run_id'], run)
        self.assertTrue(reread['payload']['plan_product']['consumed'])
        self.reviewed_pair(reread['payload'])
        self.assertFalse(reread['natural_verified'])

    def test_target_nine_explicit_missing_pair_cannot_relabel_target_eight_package(self):
        self.request.update(target_date='20261009', announcement_date='20261008')
        payload = run_manager_plan(self.request)['payload']
        reviewed = payload['announcement_reviewed_analysis']
        self.assertEqual(reviewed['consumed_product_sha256s'], [])
        self.assertEqual(len(reviewed['products']), 1)
        item = reviewed['products'][0]
        self.assertEqual((item['target_trade_date'], item['publication_date']), ('20261009','2026-10-08'))
        self.assertEqual(item['status'], 'NOT_IMPORTED')
        self.assertFalse(item['consumed'])
        self.assertIsNone(item['selected_stock_count'])


if __name__ == '__main__':unittest.main()
