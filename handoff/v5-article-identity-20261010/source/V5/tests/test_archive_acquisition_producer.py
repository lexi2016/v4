"""Mac candidate: real original producer IO, synthetic bounded fetch/analyzer only.
Set V5_ARCHIVE_PRODUCER_SOURCE_ROOT to the existing isolated full V4 source copy.
No real CLI/network, no V4 data root; every test writes only its temporary root.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

BASE=Path(__file__).resolve().parents[1]
SOURCE=BASE/'producers/archive-acquisition-v2/source/ops/run_zsxq_hourly_delta.py'


class ArchiveAcquisitionProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(os.environ['V5_ARCHIVE_PRODUCER_SOURCE_ROOT']).resolve()
        if not (root/'infrastructure/data_store.py').is_file():
            raise ValueError('COMPLETE_ORIGINAL_SOURCE_ROOT_REQUIRED')
        manifest=json.loads((SOURCE.parents[2]/'manifest.json').read_text())
        for relative,expected in manifest['test_dependency_sha256'].items():
            if hashlib.sha256((root/relative).read_bytes()).hexdigest()!=expected:
                raise ValueError('ORIGINAL_DEPENDENCY_SHA_MISMATCH:'+relative)
        cls.old_path=list(sys.path);sys.path.insert(0,str(root))
        spec=importlib.util.spec_from_file_location('v5_archive_producer_candidate',SOURCE)
        cls.owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.owner)

    @classmethod
    def tearDownClass(cls):
        sys.path[:]=cls.old_path

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'.v5-archive-acquisition').write_text('v5.archive-acquisition.v2\n')
        self.times=['2026-10-10T10:01:00+08:00','2026-10-10T10:02:00+08:00','2026-10-10T10:03:00+08:00']
        self.fetched={'topics':[{'topic_id':'synthetic','create_time':'2026-10-09T08:00:00+08:00','content':'synthetic raw body'}],
                      'bounded_has_more':True,'page_count':1,'group_results':[]}

    def run_owner(self,**kwargs):
        # Historical now must NOT supply any new acquisition clock.
        return self.owner.materialize_zsxq_hourly_delta(data_root=self.root,trade_date='20261009',slot='0900',
            now=datetime.fromisoformat('2026-10-09T09:00:00+08:00'),
            analyzer=lambda *args:{'effective_topic_count':1,'effective_topics':[]},**kwargs)

    def test_real_producer_binds_new_bytes_and_measures_completion_not_legacy_fetched(self):
        with patch.object(self.owner,'collect_paginated_topics',return_value=self.fetched),patch.object(self.owner,'_acquisition_clock',side_effect=self.times):
            value=self.run_owner()
        ref=value['acquisition_evidence_v2'];raw=(self.root/ref['path']).read_bytes();receipt=json.loads(raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),ref['sha256'])
        self.assertEqual(receipt['retrieval_completed_at'],self.times[1])
        self.assertEqual(receipt['source_payloads_available_at'],self.times[2])
        self.assertTrue(value['fetched_at'].startswith('2026-10-09'))
        self.assertTrue(receipt['retrieval_completed_at'].startswith('2026-10-10'))
        self.assertFalse(receipt['article_acquisition_verified']);self.assertFalse(receipt['issuer_body_binding_verified'])
        for name,binding in receipt['files'].items():
            self.assertEqual(hashlib.sha256((self.root/name).read_bytes()).hexdigest(),binding['sha256'])
        self.assertTrue(receipt['bounded_has_more']);self.assertFalse(receipt['full_source_coverage'])
        recent=json.loads((self.root/value['paths']['run_dir']/'zsxq_recent_topics.json').read_bytes())
        self.assertNotIn('retrieved_at',recent['topics_brief'][0])
        self.assertNotIn('available_at',recent['topics_brief'][0])

    def test_existing_v1_success_is_reused_without_backfilling_a_receipt(self):
        path=self.root/'research_module/runtime_outputs/zsxq_hourly/20261009/0900/v35_zsxq_hourly_status_20261009_0900.json'
        path.parent.mkdir(parents=True);raw=b'{"fetch_ok":true,"status":"READY","fetched_at":"2026-10-09T09:00:00+08:00"}';path.write_bytes(raw)
        with patch.object(self.owner,'collect_paginated_topics') as fetch,patch.object(self.owner,'_acquisition_clock') as clock:
            value=self.run_owner()
        fetch.assert_not_called();clock.assert_not_called();self.assertTrue(value['reused'])
        self.assertNotIn('acquisition_evidence_v2',value);self.assertEqual(path.read_bytes(),raw)
        self.assertFalse(list(self.root.rglob('acquisition_receipt.v3.json')))

    def test_unmarked_root_is_rejected_before_fetch(self):
        (self.root/'.v5-archive-acquisition').unlink()
        with patch.object(self.owner,'collect_paginated_topics') as fetch:
            with self.assertRaises(FileNotFoundError):self.run_owner()
        fetch.assert_not_called()

    def test_failed_fetch_never_publishes_success_or_acquisition(self):
        with patch.object(self.owner,'collect_paginated_topics',side_effect=RuntimeError('synthetic fetch failure')):
            with self.assertRaisesRegex(RuntimeError,'synthetic fetch failure'):self.run_owner()
        self.assertFalse(list(self.root.rglob('acquisition_receipt.v3.json')))
        self.assertFalse(list(self.root.rglob('latest_zsxq_hourly_status.json')))

    def test_clock_rollback_retains_payload_but_does_not_publish_ready_status(self):
        times=[self.times[1],self.times[0],self.times[2]]
        with patch.object(self.owner,'collect_paginated_topics',return_value=self.fetched),patch.object(self.owner,'_acquisition_clock',side_effect=times):
            with self.assertRaisesRegex(ValueError,'CLOCK_ORDER'):self.run_owner()
        self.assertTrue(list(self.root.rglob('zsxq_recent_topics.json')))
        self.assertFalse(list(self.root.rglob('latest_zsxq_hourly_status.json')))

    def test_mismatching_persisted_bytes_block_receipt_and_status(self):
        original=self.owner.NativeDataStore._write
        def write(store,path,value):
            if path.endswith('zsxq_summary.json'):value={**value,'unexpected':'changed after computation'}
            return original(store,path,value)
        with patch.object(self.owner,'collect_paginated_topics',return_value=self.fetched),patch.object(self.owner,'_acquisition_clock',side_effect=self.times),patch.object(self.owner.NativeDataStore,'_write',write):
            with self.assertRaisesRegex(ValueError,'PAYLOAD_READBACK_MISMATCH'):self.run_owner()
        self.assertFalse(list(self.root.rglob('acquisition_receipt.v3.json')))
        self.assertFalse(list(self.root.rglob('latest_zsxq_hourly_status.json')))
