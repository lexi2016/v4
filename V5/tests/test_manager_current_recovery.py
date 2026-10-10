"""Actual adapter recovery reads; synthetic empty owners, no business evidence."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen

from v5_shadow.contracts import aware
from v5_shadow.digests import canonical_bytes
from v5_shadow.manager_plan import ROUTE, publish_workspace_read, run_manager_plan
from v5_shadow.module_api import create_module_server


class ManagerCurrentRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='v5-current-recovery-test-')
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
        # Keep the original old target. The cross-day case must use the actual
        # current clock; moving this fixture's date would conceal the blocker.
        self.request = dict(target_date='20261009', now=datetime.now(timezone.utc).isoformat(),
            action='refresh', view='auto', selection_date=None, announcement_date=None,
            inputs=inputs, rebound=None, manager_output_root=str(self.output))
        self.assertGreater(self.request['now'][:10], '2026-10-09')

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def read(self, **changes):
        return run_manager_plan(dict(self.request, action='read', **changes))

    def test_crossday_refresh_and_auto_read_keep_same_run_and_sha(self):
        saved = run_manager_plan(self.request)
        page = self.read()
        self.assertEqual(saved['readback']['run_id'], page['payload']['plan_product']['run_id'])
        self.assertEqual(saved['readback']['plan_sha256'], page['payload']['plan_product']['sha256'])
        for result in (saved, page):
            self.assertEqual(result['payload']['plan_product']['status'], 'CURRENT_RECOVERY')
            self.assertTrue(result['payload']['plan_product']['consumed'])
            context = result['payload']['read_context']
            self.assertEqual(context['mode'], 'CURRENT_RECOVERY')
            self.assertEqual(context['requested_view'], 'auto')
            self.assertEqual(context['owner_view'], 'dynamic')
            self.assertFalse(context['historical_eligible'])
            self.assertEqual(aware(context['read_as_of']), aware(self.request['now']))

    def test_recovery_uses_actual_cutoff_and_actual_generated_time(self):
        before = datetime.now(timezone.utc)
        saved = run_manager_plan(self.request)
        after = datetime.now(timezone.utc)
        self.assertEqual(saved['readback']['store_relative'], 'current_recovery')
        run = saved['readback']['run_id']
        plan = json.loads((self.output / 'current_recovery' / 'workspace_plans' /
                           '20261009' / (run + '.json')).read_bytes())
        self.assertEqual(aware(plan['workspace']['plan_context']['research_cutoff']),
                         aware(self.request['now']))
        self.assertLessEqual(before, aware(plan['generated_at']))
        self.assertLessEqual(aware(plan['generated_at']), after)
        self.assertFalse((self.output / 'workspace_plans').exists())
        self.assertFalse(plan['production_allowed'])
        self.assertFalse(plan['buy_gate_updated'])
        self.assertFalse(plan['orders_sent'])

    def test_same_day_owner_plan_keeps_original_store_and_identity(self):
        request = dict(self.request, now='2026-10-09T08:45:00+08:00')
        saved = run_manager_plan(request)
        page = run_manager_plan(dict(request, action='read', now='2026-10-09T08:50:00+08:00'))
        self.assertEqual(page['payload']['plan_product']['status'], 'CURRENT')
        self.assertEqual(saved['readback']['run_id'], page['payload']['plan_product']['run_id'])
        self.assertEqual(saved['readback']['plan_sha256'], page['payload']['plan_product']['sha256'])
        self.assertEqual(saved['readback']['store_relative'], '.')
        self.assertFalse((self.output / 'current_recovery').exists())

    def test_crossday_recovery_preserves_every_existing_original_plan_byte(self):
        original = run_manager_plan(dict(self.request, now='2026-10-09T08:45:00+08:00'))
        before = self.snapshot()
        saved = run_manager_plan(self.request)
        self.assertNotEqual(original['readback']['run_id'], saved['readback']['run_id'])
        self.assertEqual(saved['readback']['store_relative'], 'current_recovery')
        after = self.snapshot()
        for path, raw in before.items():
            self.assertEqual(after[path], raw, path)
        self.assertEqual(saved['readback']['run_id'], self.read()['payload']['plan_product']['run_id'])

    def test_explicit_history_cannot_consume_a_recovery_plan(self):
        run_manager_plan(self.request)
        before = self.snapshot()
        historical = self.read(view='historical')['payload']
        self.assertEqual(historical['read_context']['mode'], 'HISTORICAL_AS_OF')
        self.assertEqual(historical['plan_product']['status'], 'NOT_MATERIALIZED')
        self.assertEqual(historical['plan_product']['reason'], 'HISTORY_QUALIFIED_SAVED_PLAN_MISSING')
        self.assertFalse(historical['plan_product']['consumed'])
        self.assertIsNone(historical['plan_product']['run_id'])
        self.assertEqual(self.snapshot(), before)

    def test_auto_without_recovery_keeps_original_missing_history_gate(self):
        before = self.snapshot()
        page = self.read()['payload']
        self.assertEqual(page['read_context']['mode'], 'HISTORICAL_AS_OF')
        self.assertEqual(page['plan_product']['reason'], 'HISTORY_QUALIFIED_SAVED_PLAN_MISSING')
        self.assertFalse(page['plan_product']['consumed'])
        self.assertEqual(self.snapshot(), before)

    def test_recovery_for_another_target_does_not_select_this_target(self):
        run_manager_plan(dict(self.request, target_date='20261008'))
        before = self.snapshot()
        page = self.read()['payload']
        self.assertEqual(page['read_context']['mode'], 'HISTORICAL_AS_OF')
        self.assertEqual(page['plan_product']['reason'], 'HISTORY_QUALIFIED_SAVED_PLAN_MISSING')
        self.assertIsNone(page['plan_product']['run_id'])
        self.assertEqual(self.snapshot(), before)

    def test_repeated_auto_read_preserves_files_run_and_sha(self):
        saved = run_manager_plan(self.request)
        before = self.snapshot()
        for _ in range(3):
            page = self.read()['payload']['plan_product']
            self.assertEqual(page['run_id'], saved['readback']['run_id'])
            self.assertEqual(page['sha256'], saved['readback']['plan_sha256'])
            self.assertTrue(page['consumed'])
        self.assertEqual(self.snapshot(), before)

    def test_recovery_attempt_tampering_cannot_claim_consumption(self):
        saved = run_manager_plan(self.request)
        path = self.output / saved['readback']['store_relative'] / 'workspace_plan_runs' / '20261009' / (saved['readback']['run_id'] + '.json')
        attempt = json.loads(path.read_bytes())
        attempt['run_id'] = '2' * 32
        from v5_shadow.digests import sha256_json
        attempt['sha256'] = sha256_json({key: value for key, value in attempt.items() if key != 'sha256'})
        path.write_bytes(canonical_bytes(attempt))
        before = self.snapshot()
        page = self.read()['payload']
        self.assertEqual(page['plan_product']['status'], 'OWNER_ATTEMPT_UNVERIFIED')
        self.assertFalse(page['plan_product']['consumed'])
        self.assertEqual(page['read_context']['mode'], 'CURRENT_RECOVERY')
        self.assertEqual(self.snapshot(), before)

    def assert_missing_recovery_journal_rejected(self, saved):
        before = self.snapshot()
        page = self.read()['payload']
        self.assertFalse(page['plan_product']['consumed'])
        self.assertEqual(page['plan_product']['status'], 'OWNER_ATTEMPT_UNVERIFIED')
        self.assertEqual(page['plan_product']['reason'], 'CURRENT_RECOVERY_EXACT_OWNER_ATTEMPT_MISSING')
        self.assertEqual(page['plan_product']['run_id'], saved['readback']['run_id'])
        self.assertEqual(page['plan_product']['sha256'], saved['readback']['plan_sha256'])
        self.assertEqual(page['read_context']['mode'], 'CURRENT_RECOVERY')
        for channel in page['daily_channels']['channels']:
            if channel['channel'] in ('HK_CONNECT', 'OVERSOLD'):
                self.assertIsNone(channel['run_id'])
                self.assertIsNone(channel['product_sha256'])
                self.assertEqual(channel['attempt_status'], 'NOT_VERIFIED')
                self.assertEqual(channel['execution_kind'], 'READ_ONLY_EXISTING_OWNER_REPLAY')
        self.assertEqual(self.snapshot(), before)

    def test_missing_exact_recovery_journal_is_rejected_despite_latest_journal(self):
        saved = run_manager_plan(self.request)
        journal = self.output / 'current_recovery' / 'workspace_plan_runs' / '20261009' / (saved['readback']['run_id'] + '.json')
        journal.unlink()
        self.assertTrue(journal.with_name('latest.json').is_file())
        self.assert_missing_recovery_journal_rejected(saved)

    def test_missing_exact_and_latest_recovery_journals_are_rejected(self):
        saved = run_manager_plan(self.request)
        journal = self.output / 'current_recovery' / 'workspace_plan_runs' / '20261009' / (saved['readback']['run_id'] + '.json')
        journal.unlink()
        journal.with_name('latest.json').unlink()
        self.assert_missing_recovery_journal_rejected(saved)

    def test_same_day_manual_missing_journal_keeps_fresh_preview_without_consumption(self):
        request = dict(self.request, now='2026-10-09T08:45:00+08:00')
        fresh = run_manager_plan(dict(request, action='read'))['payload']
        saved = run_manager_plan(request)
        journal = self.output / 'workspace_plan_runs' / '20261009' / (saved['readback']['run_id'] + '.json')
        journal.unlink()
        journal.with_name('latest.json').unlink()
        before = self.snapshot()
        page = run_manager_plan(dict(request, action='read'))['payload']
        self.assertEqual(page['plan_product']['status'], 'OWNER_ATTEMPT_UNVERIFIED')
        self.assertEqual(page['plan_product']['reason'], 'MANAGER_EXACT_OWNER_ATTEMPT_MISSING')
        self.assertFalse(page['plan_product']['consumed'])
        self.assertEqual(page['plan_product']['run_id'], saved['readback']['run_id'])
        self.assertEqual(page['plan_product']['sha256'], saved['readback']['plan_sha256'])
        self.assertIsNone(page['workspace_plan_attempt'])
        for name in ('stocks', 'materials', 'announcement_reviewed_analysis', 'input_identity'):
            self.assertEqual(page[name], fresh[name], name)
        for channel in page['daily_channels']['channels']:
            if channel['channel'] in ('HK_CONNECT', 'OVERSOLD'):
                self.assertIsNone(channel['run_id'])
                self.assertIsNone(channel['product_sha256'])
                self.assertEqual(channel['attempt_status'], 'NOT_VERIFIED')
        self.assertEqual(self.snapshot(), before)

    def test_changed_bound_input_bytes_still_fail_sha_admission(self):
        request = copy.deepcopy(self.request)
        relative = 'workspace_announcements/20261009/latest.json'
        path = Path(request['inputs']['manager']['root']) / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(b'{}')
        request['inputs']['manager']['files'][relative] = hashlib.sha256(b'{}').hexdigest()
        path.write_bytes(b'{"changed":true}')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'MANAGER_INPUT_SHA_OR_LIMIT'):
            run_manager_plan(request)
        self.assertEqual(self.snapshot(), before)

    def test_future_now_is_rejected_without_creating_a_store(self):
        before = self.snapshot()
        request = dict(self.request, now=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        with self.assertRaisesRegex(ValueError, 'MANAGER_FUTURE_CUTOFF'):
            run_manager_plan(request)
        self.assertEqual(self.snapshot(), before)

    def test_recovery_directory_symlink_is_rejected_without_writing_outside(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.output / 'current_recovery').symlink_to(outside, target_is_directory=True)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'SYMLINK_REJECTED'):
            run_manager_plan(self.request)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(outside.iterdir()), [])

    def test_ordinary_auto_http_get_keeps_saved_recovery_run_and_sha(self):
        saved = run_manager_plan(self.request)
        api = self.root / 'api'
        api.mkdir()
        (api / '.v5-module-root').write_bytes(b'v5.module-root.v1:manager\n')
        config = dict(schema_version='v5.module_api.v1', module_id='manager', release_id='recovery-test',
            data_root=str(api), routes=[ROUTE])
        published = publish_workspace_read(dict(self.request, action='read'), config, expected_generation=None)
        server = create_module_server(config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        before = self.snapshot()
        url = 'http://127.0.0.1:' + str(server.server_port) + ROUTE + '?date=20261009&view=auto'
        with urlopen(url, timeout=5) as response:
            page = json.load(response)
        self.assertEqual(page, published['result']['payload'])
        self.assertEqual(page['plan_product']['status'], 'CURRENT_RECOVERY')
        self.assertEqual(page['plan_product']['run_id'], saved['readback']['run_id'])
        self.assertEqual(page['plan_product']['sha256'], saved['readback']['plan_sha256'])
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
