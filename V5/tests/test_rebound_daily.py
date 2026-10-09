"""Mac-only regression candidates for daily orchestration, no market requests.

The owner is stubbed here to isolate claim/readback behavior. Existing opt-in
test_rebound_observation cases exercise the actual frozen owner separately.
"""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v5_shadow import rebound_daily as daily
from v5_shadow.digests import sha256_json


class DailyOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'output'
        self.output.mkdir()
        (self.output / '.v5-rebound-observation-root').write_bytes(daily.observation.MARKER)
        self.request = dict(input_root=str(self.root / 'input'), target_date='20261009',
                            signal_date='20261008', data_kind='RECORDED_INPUT_CURRENT')
        self.identity = dict(observation={'test.py': 'a'*64}, dependencies={'status': 'MATCH'},
                             capsule_sha256='b'*64, daily_sha256='c'*64)
        self.artifacts = {}
        self.calls = 0
        for target, replacement in (
            ('_prepare', self.prepare), ('_identity', lambda: copy.deepcopy(self.identity)),
            ('build_recovery_plan', lambda value: {'source_run_id': value['run_id']}),
        ):
            mock = patch.object(daily, target, side_effect=replacement)
            mock.start(); self.addCleanup(mock.stop)
        mock = patch.object(daily.observation, 'read_rebound_observation',
                            side_effect=lambda root, ref: copy.deepcopy(self.artifacts[ref['run_id']]))
        mock.start(); self.addCleanup(mock.stop)

    def prepare(self, request, *, reconciliation=False):
        return copy.deepcopy(request), copy.deepcopy(self.identity), sha256_json(dict(request=request, identity=self.identity))

    def worker(self, request, root):
        self.calls += 1
        now = datetime.now(timezone.utc).isoformat()
        run = str(self.calls).zfill(32)
        artifact = dict(run_id=run, request=copy.deepcopy(request), started_at=now, finished_at=now,
            implementation_identity=self.identity['observation'], dependencies=self.identity['dependencies'],
            source_capsule_sha256=self.identity['capsule_sha256'], computation_status='NATIVE_VALUES_OBSERVED',
            counts={'observed_rows': 695, 'numeric_input_complete': 0, 'numeric_input_incomplete': 695},
            reason_codes=['SYNTHETIC_ORCHESTRATION_FIXTURE'])
        self.artifacts[run] = artifact
        return dict(reference={'run_id': run})

    def test_same_input_reuses_committed_observation_without_claiming_selection(self):
        with patch.object(daily.observation, 'run_rebound_observation', side_effect=self.worker):
            first = daily.run_rebound_daily(self.request, self.output)
            again = daily.run_rebound_daily(self.request, self.output)
        self.assertEqual(self.calls, 1)
        self.assertFalse(first['reused']); self.assertTrue(again['reused'])
        self.assertEqual(first['reference'], again['reference'])
        self.assertEqual(first['selection_status'], 'CANNOT_CONFIRM')
        self.assertIsNone(first['eligible_screen'])
        self.assertFalse(first['natural_verified']); self.assertFalse(first['scheduler_installed'])

    def test_input_and_implementation_changes_get_new_calculation_keys(self):
        with patch.object(daily.observation, 'run_rebound_observation', side_effect=self.worker):
            one = daily.run_rebound_daily(self.request, self.output)
            self.request['new_input_sha'] = 'd'*64
            two = daily.run_rebound_daily(self.request, self.output)
            self.identity['daily_sha256'] = 'e'*64
            three = daily.run_rebound_daily(self.request, self.output)
        self.assertEqual(self.calls, 3)
        self.assertEqual(len({one['daily_key'], two['daily_key'], three['daily_key']}), 3)

    def test_readback_mismatch_keeps_indeterminate_claim(self):
        def bad(request, root):
            result = self.worker(request, root)
            self.artifacts[result['reference']['run_id']]['request'] = {'wrong': True}
            return result
        with patch.object(daily.observation, 'run_rebound_observation', side_effect=bad):
            with self.assertRaisesRegex(ValueError, 'REQUEST_CHANGED'):
                daily.run_rebound_daily(self.request, self.output)
        with self.assertRaisesRegex(ValueError, 'RECONCILIATION_REQUIRED'):
            daily.run_rebound_daily(self.request, self.output)

    def test_interrupted_success_can_be_explicitly_reconciled_without_recompute(self):
        reference = None
        def crash(request, root):
            nonlocal reference
            reference = self.worker(request, root)['reference']
            raise RuntimeError('simulated process interruption after committed owner output')
        with patch.object(daily.observation, 'run_rebound_observation', side_effect=crash):
            with self.assertRaises(RuntimeError): daily.run_rebound_daily(self.request, self.output)
            with self.assertRaisesRegex(ValueError, 'RECONCILIATION_REQUIRED'):
                daily.run_rebound_daily(self.request, self.output)
        result = daily.reconcile_rebound_daily(self.request, self.output, reference)
        self.assertTrue(result['reused']); self.assertEqual(self.calls, 1)
        self.assertEqual(daily.run_rebound_daily(self.request, self.output)['reference'], reference)

    def test_failed_computation_remains_retryable_and_is_not_cached_as_success(self):
        def failed(request, root):
            result = self.worker(request, root)
            self.artifacts[result['reference']['run_id']]['computation_status'] = 'CANNOT_CONFIRM'
            return result
        with patch.object(daily.observation, 'run_rebound_observation', side_effect=failed):
            one = daily.run_rebound_daily(self.request, self.output)
            two = daily.run_rebound_daily(self.request, self.output)
        self.assertEqual(self.calls, 2)
        self.assertFalse(one['reused']); self.assertFalse(two['reused'])
        self.assertIsNone(one['recovery_plan'])

    def test_interrupted_failed_reference_can_be_reconciled_repeatedly_then_retried(self):
        reference = None
        def crash(request, root):
            nonlocal reference
            reference = self.worker(request, root)['reference']
            self.artifacts[reference['run_id']]['computation_status'] = 'CANNOT_CONFIRM'
            self.artifacts[reference['run_id']].pop('dependencies')
            raise RuntimeError('interrupted failed owner receipt')
        with patch.object(daily.observation, 'run_rebound_observation', side_effect=crash):
            with self.assertRaises(RuntimeError): daily.run_rebound_daily(self.request, self.output)
        for _ in range(2):
            result = daily.reconcile_rebound_daily(self.request, self.output, reference)
            self.assertEqual(result['computation_status'], 'CANNOT_CONFIRM')
        with patch.object(daily.observation, 'run_rebound_observation', side_effect=self.worker):
            result = daily.run_rebound_daily(self.request, self.output)
        self.assertFalse(result['reused']); self.assertEqual(self.calls, 2)

    def test_concurrent_same_key_is_busy_without_waiting(self):
        _, _, key = self.prepare(self.request)
        with daily._locked(self.output, key, self.request['input_root']):
            with self.assertRaisesRegex(ValueError, 'BUSY'):
                daily.run_rebound_daily(self.request, self.output)

    def test_overlap_rejected_before_any_daily_file_is_created(self):
        with self.assertRaisesRegex(ValueError, 'ROOT_OVERLAP'):
            with daily._locked(self.output, 'a'*64, str(self.root)):
                self.fail('overlap admitted')
        self.assertFalse((self.output / 'daily').exists())


class DailyInputTests(unittest.TestCase):
    def test_readback_only_reconciliation_can_cross_actual_date(self):
        value = dict(data_kind='RECORDED_INPUT_CURRENT', input_root='/unused-test-input',
                     target_date='20000101', files={'panel': 'a'*64})
        with patch.object(daily.observation, '_request', return_value=value), \
             patch.object(daily.owner, '_file', return_value={'sha256': 'a'*64}), \
             patch.object(daily.observation, '_capsule'), patch.object(daily, '_identity', return_value={}):
            self.assertEqual(daily._prepare(value, reconciliation=True)[0], value)
            with self.assertRaisesRegex(ValueError, 'CURRENT_TARGET_REQUIRED'): daily._prepare(value)

    def test_prepare_rejects_replay_synthetic_and_wrong_actual_day(self):
        base = dict(data_kind='RECORDED_INPUT_CURRENT', target_date='20000101', files={})
        for kind in ('SYNTHETIC', 'RECORDED_INPUT_REPLAY', 'RECORDED_INPUT_CURRENT'):
            value = dict(base, data_kind=kind)
            with patch.object(daily.observation, '_request', return_value=value):
                with self.assertRaises(ValueError): daily._prepare(value)

    def test_reuse_checks_current_source_bytes_even_before_cached_result(self):
        value = dict(data_kind='RECORDED_INPUT_CURRENT', input_root='/unused-test-input',
                     target_date=datetime.now(daily.observation.HK).strftime('%Y%m%d'), files={'panel': 'a'*64})
        with patch.object(daily.observation, '_request', return_value=value), \
             patch.object(daily.owner, '_file', return_value={'sha256': 'b'*64}):
            with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'): daily._prepare(value)


if __name__ == '__main__':
    unittest.main()
