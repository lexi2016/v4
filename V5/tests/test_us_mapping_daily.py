"""Original daily US mapping must build, persist and independently read back."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone


class UsMappingDailyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('V5_US_MAPPING_REQUEST_PATH')
        if not path:
            raise RuntimeError('V5_US_MAPPING_REQUEST_PATH_REQUIRED_NO_SKIP')
        cls.base_request = json.loads(Path(path).read_text())

    def request(self, *, copy_inputs=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        request = copy.deepcopy(self.base_request)
        output = root / 'manager'
        output.mkdir()
        (output / '.v5-us-mapping-root').write_text('v5.us-mapping-root.v1\n')
        request['manager_output_root'] = str(output)
        if copy_inputs:
            source = Path(request['us_data_root'])
            target = root / 'inputs'
            target.mkdir()
            for name, digest in request['us_files'].items():
                raw = (source / name).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
            request['us_data_root'] = str(target)
        return request

    def run_owner(self, request):
        from v5_shadow.us_mapping_daily import run_us_mapping
        return run_us_mapping(request)

    def test_original_build_persist_and_independent_readback(self):
        request = self.request()
        result = self.run_owner(request)
        self.assertEqual(result['schema_version'], 'v5.us_mapping_daily.v1')
        daily = result['payload']['daily_run']
        self.assertEqual(daily['target_trade_date'], request['target_date'])
        self.assertEqual(daily['us_session_date'], '20261007')
        self.assertRegex(daily['run_id'], r'^[0-9a-f]{32}$')
        self.assertEqual(result['persisted_daily'], daily)
        self.assertEqual(result['readback_status'], 'MATCHED')
        self.assertIn(daily['status'], ('COMPLETED', 'VALID_EMPTY', 'PARTIAL', 'CANNOT_CONFIRM', 'INPUT_MISSING', 'FAILED'))
        self.assertFalse(result['natural_verified'])
        self.assertFalse(result['source_origin_verified'])
        self.assertFalse(daily['production_allowed'])
        self.assertFalse(daily['orders_sent'])
        self.assertEqual(daily['target_date_eligibility'], 'CANNOT_CONFIRM')
        self.assertFalse(daily['coverage']['full_market_coverage'])
        self.assertEqual(result['input_sha_before'], result['input_sha_after'])
        self.assertEqual(result['input_sha_before'], request['us_files'])

    def test_execution_time_is_not_backdated_to_research_cutoff(self):
        request = self.request()
        before = datetime.now(timezone.utc)
        result = self.run_owner(request)
        after = datetime.now(timezone.utc)
        generated = datetime.fromisoformat(result['payload']['daily_run']['generated_at'].replace('Z', '+00:00'))
        self.assertGreaterEqual(generated.timestamp(), before.timestamp() - 1)
        self.assertLessEqual(generated, after)
        cutoff = datetime.fromisoformat(result['payload']['daily_run']['research_cutoff'])
        self.assertEqual(cutoff, datetime.fromisoformat(request['now']))
        self.assertEqual(result['execution_kind'], 'MANUAL_RECOVERY')

    def test_source_copy_receives_no_owner_lock_or_other_write(self):
        request = self.request(copy_inputs=True)
        source = Path(request['us_data_root'])
        before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        self.run_owner(request)
        after = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_changed_source_bytes_rejected(self):
        request = self.request(copy_inputs=True)
        path = Path(request['us_data_root']) / next(iter(request['us_files']))
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_owner(request)

    def test_missing_receipt_not_admitted(self):
        request = self.request()
        request['us_files'] = {k: v for k, v in request['us_files'].items() if not k.startswith('receipts/')}
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_owner(request)

    def test_wrong_session_paths_rejected(self):
        request = self.request()
        request['us_files'] = {k.replace('20261007', '20260930'): v for k, v in request['us_files'].items()}
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_owner(request)

    def test_naive_cutoff_rejected(self):
        request = self.request()
        request['now'] = '2026-10-08T09:27:00'
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_owner(request)

    def test_output_without_v5_marker_rejected(self):
        request = self.request()
        (Path(request['manager_output_root']) / '.v5-us-mapping-root').unlink()
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_owner(request)

    def test_overlapping_source_and_output_rejected(self):
        request = self.request()
        request['manager_output_root'] = request['us_data_root']
        with self.assertRaises((ValueError, RuntimeError)):
            self.run_owner(request)

    def test_two_manual_attempts_preserve_original_runs(self):
        request = self.request()
        first = self.run_owner(request)['payload']['daily_run']
        second = self.run_owner(request)['payload']['daily_run']
        self.assertNotEqual(first['run_id'], second['run_id'])
        runs = Path(request['manager_output_root']) / 'us_mapping_research' / request['target_date'] / 'runs'
        for value in (first, second):
            saved = json.loads((runs / (value['run_id'] + '.json')).read_bytes())
            self.assertEqual(saved, value)


if __name__ == '__main__':
    unittest.main()
