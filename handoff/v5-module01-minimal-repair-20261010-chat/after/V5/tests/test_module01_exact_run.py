"""Real pinned owner/store interleavings; empty inputs are not business evidence.

The test seams only pause or corrupt an isolated durable result after the real
owner has returned. No replacement owner, store, validator, or source reader is
used. Reverting the exact reader makes a completed A fail when B advances latest;
reverting the ordinary-read binding displays B's journal beside A's product.
"""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest

from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.manager_plan import run_manager_plan


SOURCE = Path(__file__).resolve().parents[1] / 'src'
CHILD = r'''
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from v5_shadow import manager_plan
from v5_shadow.digests import canonical_bytes

request = json.loads(sys.stdin.buffer.readline())
mode = sys.argv[2]
load_owner = manager_plan.load_owner

def instrument_owner():
    owner = load_owner()
    if mode == 'pause_read':
        read_plan = owner._read_plan
        paused = False
        def pause_after_plan(store, date):
            nonlocal paused
            saved = read_plan(store, date)
            if not paused:
                paused = True
                sys.stderr.write('EXACT_RUN_READ_PAUSED\n')
                sys.stderr.flush()
                if sys.stdin.buffer.readline() != b'CONTINUE\n':
                    raise ValueError('TEST_READ_HANDSHAKE_FAILED')
            return saved
        owner._read_plan = pause_after_plan
        return owner
    refresh = owner.refresh_workspace_plan
    def after_real_save(service, date, **kwargs):
        first = refresh(service, date, **kwargs)
        run = first['plan_product']['run_id']
        root, _ = manager_plan._plan_store_scope(request, owner.HK)
        plans = service.store.root / 'workspace_plans' / date
        journals = service.store.root / 'workspace_plan_runs' / date
        if mode in {'advance_latest', 'other_terminal_missing', 'borrow_terminal',
                    'wrong_exact_run', 'return_other_attempt'}:
            second = refresh(service, date, **kwargs)
            other = second['plan_product']['run_id']
            if mode == 'return_other_attempt':
                first['workspace_plan_attempt'] = second['workspace_plan_attempt']
                first['daily_channels'] = second['daily_channels']
            elif mode == 'other_terminal_missing':
                os.unlink(root / 'workspace_plan_runs' / date / (other + '.json'))
            elif mode == 'borrow_terminal':
                borrowed = service.store._read(journals / (other + '.json'))
                service.store._write_atomic(journals / (run + '.json'), borrowed)
            elif mode == 'wrong_exact_run':
                borrowed = service.store._read(plans / (other + '.json'))
                os.unlink(root / 'workspace_plans' / date / (run + '.json'))
                service.store._write_atomic(plans / (run + '.json'), borrowed)
        elif mode == 'missing_terminal':
            os.unlink(root / 'workspace_plan_runs' / date / (run + '.json'))
        elif mode == 'missing_latest':
            os.unlink(root / 'workspace_plans' / date / 'latest.json')
        elif mode == 'invalid_latest':
            invalid = service.store._read(plans / 'latest.json')
            invalid['sha256'] = '0' * 64
            service.store._write_atomic(plans / 'latest.json', invalid)
        elif mode in {'invalid_exact_sha', 'wrong_exact_date'}:
            invalid = service.store._read(plans / (run + '.json'))
            if mode == 'invalid_exact_sha':
                invalid['sha256'] = '0' * 64
            else:
                invalid['target_trade_date'] = '20261007'
                invalid['workspace']['target_trade_date'] = '20261007'
                invalid['sha256'] = owner.digest({k: v for k, v in invalid.items() if k != 'sha256'})
            os.unlink(root / 'workspace_plans' / date / (run + '.json'))
            service.store._write_atomic(plans / (run + '.json'), invalid)
        elif mode == 'unsafe_returned_run':
            first['plan_product']['run_id'] = '../outside'
        return first
    owner.refresh_workspace_plan = after_real_save
    return owner

manager_plan.load_owner = instrument_owner
try:
    value = manager_plan._assemble(request)
    print(canonical_bytes(dict(ok=True, value=value)).decode())
except Exception as error:
    print(canonical_bytes(dict(ok=False, error=type(error).__name__ + ':' + str(error))).decode())
    raise SystemExit(1)
'''


class ExactManagerRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='v5-module01-exact-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        inputs = {}
        for name in ('manager', 'materials', 'us'):
            path = self.root / name
            path.mkdir()
            inputs[name] = dict(root=str(path), files={})
        self.output = self.root / 'plans'
        self.output.mkdir()
        (self.output / '.v5-manager-plan-root').write_bytes(b'v5.manager-plan-root.v1\n')
        self.request = dict(target_date='20261008', now='2026-10-09T10:00:00+08:00',
            action='refresh', view='dynamic', selection_date=None, announcement_date=None,
            inputs=inputs, rebound=None, manager_output_root=str(self.output))

    def child_command(self, mode):
        cache = tempfile.TemporaryDirectory(prefix='v5-exact-child-')
        self.addCleanup(cache.cleanup)
        return [sys.executable, '-I', '-B', '-X', 'pycache_prefix=' + cache.name,
                '-c', CHILD, str(SOURCE), mode]

    def refresh_with(self, mode):
        result = subprocess.run(self.child_command(mode), input=canonical_bytes(self.request) + b'\n',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
            env={key: value for key, value in os.environ.items() if not key.startswith('V4_')})
        try:
            body = json.loads(result.stdout)
        except ValueError:
            self.fail('Child did not return JSON: ' + result.stderr.decode(errors='replace'))
        self.assertEqual(result.returncode, 0 if body['ok'] else 1, result.stderr.decode(errors='replace'))
        return body

    def saved_plan(self, result):
        readback = result['readback']
        root = self.output / readback['store_relative']
        path = root / 'workspace_plans' / self.request['target_date'] / (readback['run_id'] + '.json')
        return json.loads(path.read_bytes())

    def assert_exact(self, result):
        payload, readback = result['payload'], result['readback']
        saved = self.saved_plan(result)
        self.assertEqual(readback['status'], 'MATCHED')
        self.assertEqual(readback['run_id'], payload['plan_product']['run_id'])
        self.assertEqual(readback['plan_sha256'], payload['plan_product']['sha256'])
        self.assertEqual(saved['sha256'], readback['plan_sha256'])
        self.assertEqual(saved['sha256'], sha256_json({k: v for k, v in saved.items() if k != 'sha256'}))
        self.assertEqual(readback['attempt']['run_id'], saved['run_id'])
        self.assertEqual(payload['workspace_plan_attempt'], readback['attempt'])
        self.assertEqual(payload['plan_context'], saved['workspace']['plan_context'])
        self.assertEqual(payload['date_bindings'], saved['workspace']['date_bindings'])
        self.assertEqual(payload['input_identity'], saved['input_identity'])
        for key in ('natural_verified', 'production_allowed', 'buy_gate_updated', 'orders_sent'):
            self.assertIs(result[key], False)
        for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'):
            self.assertIs(saved[key], False)

    def test_completed_exact_run_survives_another_real_refresh_advancing_latest(self):
        body = self.refresh_with('advance_latest')
        self.assertTrue(body['ok'], body.get('error'))
        result = body['value']
        self.assert_exact(result)
        latest = result['readback'].get('latest_observation')
        self.assertIsInstance(latest, dict, 'Completed refresh must report its separate latest observation')
        self.assertEqual(latest['status'], 'VERIFIED')
        self.assertIs(latest['matches_exact_run'], False)
        self.assertNotEqual(latest['run_id'], result['readback']['run_id'])
        self.assertEqual(latest['attempt']['run_id'], latest['run_id'])
        self.assertTrue(latest['observed_at'])

    def test_matching_latest_is_observed_with_its_own_terminal(self):
        body = self.refresh_with('none')
        self.assertTrue(body['ok'], body.get('error'))
        result = body['value']
        self.assert_exact(result)
        latest = result['readback'].get('latest_observation')
        self.assertIsInstance(latest, dict, 'Completed refresh must report its separate latest observation')
        self.assertEqual(latest['status'], 'VERIFIED')
        self.assertIs(latest['matches_exact_run'], True)
        self.assertEqual(latest['attempt'], result['readback']['attempt'])

    def test_refresh_response_uses_verified_exact_terminal_if_returned_journal_is_other_run(self):
        body = self.refresh_with('return_other_attempt')
        self.assertTrue(body['ok'], body.get('error'))
        self.assert_exact(body['value'])
        for channel in body['value']['payload']['daily_channels']['channels']:
            if channel['channel'] in {'HK_CONNECT', 'OVERSOLD'}:
                self.assertEqual(channel['run_id'], body['value']['readback']['run_id'])
                self.assertEqual(channel['product_sha256'], body['value']['readback']['plan_sha256'])

    def test_same_day_read_without_exact_terminal_keeps_fresh_preview_unverified(self):
        request = dict(self.request, now='2026-10-08T08:45:00+08:00')
        read_request = dict(request, action='read')
        fresh = run_manager_plan(read_request)['payload']
        saved = run_manager_plan(request)
        self.assertEqual(saved['readback']['store_relative'], '.')
        journal = self.output / 'workspace_plan_runs' / request['target_date'] / (saved['readback']['run_id'] + '.json')
        journal.unlink()
        self.assertTrue(journal.with_name('latest.json').is_file())
        before = {str(p.relative_to(self.output)): p.read_bytes()
                  for p in self.output.rglob('*') if p.is_file()}
        result = run_manager_plan(read_request)
        payload = result['payload']
        self.assertFalse(payload['plan_product']['consumed'])
        self.assertEqual(payload['plan_product']['status'], 'OWNER_ATTEMPT_UNVERIFIED')
        self.assertEqual(payload['plan_product']['reason'], 'MANAGER_EXACT_OWNER_ATTEMPT_MISSING')
        self.assertEqual(payload['plan_product']['run_id'], saved['readback']['run_id'])
        self.assertEqual(payload['plan_product']['sha256'], saved['readback']['plan_sha256'])
        self.assertIsNone(payload['workspace_plan_attempt'])
        for name in ('stocks', 'materials', 'announcement_reviewed_analysis', 'input_identity'):
            self.assertEqual(payload[name], fresh[name], name)
        self.assertEqual(payload['read_context']['mode'], 'CURRENT_DYNAMIC_PREVIEW')
        for channel in payload['daily_channels']['channels']:
            if channel['channel'] in {'HK_CONNECT', 'OVERSOLD'}:
                self.assertIsNone(channel['run_id'])
                self.assertIsNone(channel['product_sha256'])
                self.assertEqual(channel['attempt_status'], 'NOT_VERIFIED')
        after = {str(p.relative_to(self.output)): p.read_bytes()
                 for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_missing_latest_does_not_invalidate_completed_exact_run(self):
        body = self.refresh_with('missing_latest')
        self.assertTrue(body['ok'], body.get('error'))
        self.assert_exact(body['value'])
        latest = body['value']['readback']['latest_observation']
        self.assertEqual(latest['status'], 'MISSING')
        self.assertIsNone(latest['matches_exact_run'])

    def test_invalid_latest_does_not_invalidate_completed_exact_run(self):
        body = self.refresh_with('invalid_latest')
        self.assertTrue(body['ok'], body.get('error'))
        self.assert_exact(body['value'])
        latest = body['value']['readback']['latest_observation']
        self.assertEqual(latest['status'], 'CANNOT_CONFIRM')
        self.assertIsNone(latest['matches_exact_run'])
        self.assertIsNone(latest['run_id'])

    def test_other_run_without_its_exact_terminal_is_not_reported_verified(self):
        body = self.refresh_with('other_terminal_missing')
        self.assertTrue(body['ok'], body.get('error'))
        self.assert_exact(body['value'])
        latest = body['value']['readback']['latest_observation']
        self.assertEqual(latest['status'], 'CANNOT_CONFIRM')
        self.assertNotEqual(latest['run_id'], body['value']['readback']['run_id'])
        self.assertIsNone(latest['attempt'])

    def test_exact_product_sha_is_checked_even_when_latest_copy_is_valid(self):
        body = self.refresh_with('invalid_exact_sha')
        self.assertFalse(body['ok'], 'Exact product corruption was hidden by its valid latest copy')
        self.assertIn('WORKSPACE_STORED_PLAN_INVALID', body['error'])

    def test_exact_product_date_is_checked_even_when_latest_copy_is_valid(self):
        body = self.refresh_with('wrong_exact_date')
        self.assertFalse(body['ok'], 'Exact product date was hidden by its valid latest copy')
        self.assertIn('WORKSPACE_STORED_PLAN_INVALID', body['error'])

    def test_exact_filename_cannot_borrow_another_valid_run(self):
        body = self.refresh_with('wrong_exact_run')
        self.assertFalse(body['ok'])
        self.assertIn('MANAGER_INDEPENDENT_PLAN_READBACK_MISMATCH', body['error'])

    def test_missing_exact_terminal_cannot_borrow_latest_terminal(self):
        body = self.refresh_with('missing_terminal')
        self.assertFalse(body['ok'])
        self.assertIn('MANAGER_INDEPENDENT_PLAN_READBACK_MISMATCH', body['error'])

    def test_other_runs_terminal_cannot_validate_exact_product(self):
        body = self.refresh_with('borrow_terminal')
        self.assertFalse(body['ok'])
        self.assertIn('READBACK_MISMATCH', body['error'])

    def test_returned_run_id_cannot_escape_exact_date_directory(self):
        body = self.refresh_with('unsafe_returned_run')
        self.assertFalse(body['ok'])
        self.assertIn('MANAGER_', body['error'])
        self.assertFalse((self.root / 'outside').exists())

    def test_ordinary_read_keeps_exact_product_terminal_and_native_channel_identity(self):
        first = run_manager_plan(self.request)
        read_request = dict(self.request, action='read')
        process = subprocess.Popen(self.child_command('pause_read'), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={key: value for key, value in os.environ.items() if not key.startswith('V4_')})
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        process.stdin.write(canonical_bytes(read_request) + b'\n')
        process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stderr, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=30), 'Real reader did not reach the product-read seam')
            marker = process.stderr.readline()
        self.assertEqual(marker, b'EXACT_RUN_READ_PAUSED\n', marker.decode(errors='replace'))
        second = run_manager_plan(self.request)
        before = {str(p.relative_to(self.output)): p.read_bytes()
                  for p in self.output.rglob('*') if p.is_file()}
        stdout, stderr = process.communicate(input=b'CONTINUE\n', timeout=90)
        self.assertEqual(process.returncode, 0, stderr.decode(errors='replace') + stdout.decode(errors='replace'))
        body = json.loads(stdout)
        self.assertTrue(body['ok'], body.get('error'))
        result = body['value']
        payload = result['payload']
        self.assertNotEqual(first['readback']['run_id'], second['readback']['run_id'])
        self.assertEqual(payload['plan_product']['run_id'], first['readback']['run_id'])
        self.assertEqual(payload['plan_product']['sha256'], first['readback']['plan_sha256'])
        self.assertEqual(payload['workspace_plan_attempt']['run_id'], first['readback']['run_id'])
        self.assertEqual(payload['input_identity'], first['payload']['input_identity'])
        self.assertEqual(payload['plan_context'], first['payload']['plan_context'])
        self.assertEqual(payload['date_bindings'], first['payload']['date_bindings'])
        self.assertEqual(payload['read_context']['mode'], 'CURRENT_RECOVERY')
        for channel in payload['daily_channels']['channels']:
            if channel['channel'] in {'HK_CONNECT', 'OVERSOLD'}:
                self.assertEqual(channel['run_id'], first['readback']['run_id'])
                self.assertEqual(channel['product_sha256'], first['readback']['plan_sha256'])
                self.assertFalse(channel['natural_run_verified'])
        self.assertEqual(result['readback']['latest_attempt_observation']['attempt']['run_id'],
                         second['readback']['run_id'])
        self.assertEqual(result['readback']['latest_observation']['run_id'], second['readback']['run_id'])
        after = {str(p.relative_to(self.output)): p.read_bytes()
                 for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
