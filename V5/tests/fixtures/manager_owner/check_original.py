"""RED candidate: execute the complete frozen original workspace, never its service pool.

Synthetic saved daily DTOs reproduce admission bugs; they are NOT recovery/PIT
attestations. No provider, production root, deployment or trading is used.
Run this file alone: its original-owner namespace is private to this process.
"""
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[3]
FIXTURE = BASE / 'tests/fixtures/manager_owner'
DAY = '20261008'
CURRENT = datetime.fromisoformat('2026-10-09T10:00:00+08:00')
PREOPEN = datetime.fromisoformat('2026-10-08T09:20:00+08:00')


class ManagerPlanDateGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if any(name == 'v4' or name.startswith('v4.') for name in sys.modules):
            raise RuntimeError('RUN_MANAGER_DATE_GATE_IN_A_FRESH_PROCESS')
        cls.sources = tempfile.TemporaryDirectory(prefix='v5-manager-red-source-')
        cls.addClassCleanup(cls.sources.cleanup)
        root = Path(cls.sources.name)
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        for entry in manifest['entries']:
            raw = (BASE / entry['local_path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise RuntimeError('MANAGER_RED_ORIGINAL_SOURCE_SHA:' + entry['relative_path'])
            target = root / entry['relative_path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        sys.path.insert(0, str(root))
        cls.addClassCleanup(sys.path.remove, str(root))
        cls.w = importlib.import_module('v4.manager_research.workspace')
        cls.mapping = importlib.import_module('v4.manager_research.us_mapping_research')
        cls.store_type = importlib.import_module('v4.manager_research.store').ManagerResearchStore
        cls.calendar = importlib.import_module('contracts.us_equity_calendar')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v5-manager-red-store-')
        self.addCleanup(self.tmp.cleanup)
        # No ambient V4 root may enter the fixture, even on the existing Mac.
        env = {key: value for key, value in os.environ.items() if not key.startswith('V4_')}
        self.env = patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.service = SimpleNamespace(
            store=self.store_type(Path(self.tmp.name) / 'manager'),
            observation_reader=None, _close_observation_reader=None,
            _existing_research_source=None, _catalyst_data_root=None,
            _catalyst_news_owner_root=None, _workspace_ledger_root=None,
            _workspace_security_master_root=None, _workspace_screen_authority_root=None,
            _workspace_us_market_reader=None, _material_store=None,
            get_catalyst_observations=lambda date: dict(
                status='CANNOT_CONFIRM', target_trade_date=date, cards=[],
                gaps=['SYNTHETIC_FIXTURE_CATALYST_NOT_BOUND'], **self.w.FLAGS))

    def save_daily(self, *, session='20261007', status='COMPLETED', generated=None):
        daily = dict(schema_version=self.mapping.DAILY_SCHEMA,
            target_trade_date=DAY, run_id='1' * 32,
            generated_at=generated or '2026-10-09T09:00:00+08:00',
            research_cutoff='2026-10-08T09:00:00.123456+08:00',
            us_session_date=session, status=status, source_status='READY',
            source_identity={'status': 'VERIFIED', 'session_date': session,
                             'payload_sha256': 'a' * 64},
            input_identity='b' * 64, target_date_eligibility='CANNOT_CONFIRM',
            coverage={'full_market_coverage': False},
            matches=[] if status == 'VALID_EMPTY' else [{'reason': 'SYNTHETIC_RELATION'}],
            gaps=['SYNTHETIC_FIXTURE_NOT_PRODUCTION_EVIDENCE'], **self.w.FLAGS)
        daily['artifact_sha256'] = self.w.digest(daily)
        store = self.service.store
        root = store.root / 'us_mapping_research' / DAY
        store._write_atomic(root / 'runs' / (daily['run_id'] + '.json'), daily)
        store._write_atomic(root / 'latest.json', dict(
            schema_version='v4.manager_research.us_mapping_daily_pointer.v1',
            target_trade_date=DAY, run_id=daily['run_id'],
            artifact_sha256=daily['artifact_sha256']))
        return daily

    def files(self):
        return {str(p.relative_to(self.service.store.root)): p.read_bytes()
                for p in self.service.store.root.rglob('*') if p.is_file()}

    def reference(self, now):
        context = self.w.plan_context(DAY, now=now)
        self.assertEqual(context['research_cutoff'], now.isoformat())
        self.assertIsNone(context['us_market_session'])
        return self.w._daily_mapping_plan_reference(self.service, DAY, context)

    def test_completed_previous_session_is_not_admitted_at_current_cutoff(self):
        daily = self.save_daily()
        self.assertEqual(self.calendar.latest_completed_session(CURRENT).session_date, '20261008')
        before = self.files()
        mapping, reference, identities = self.reference(CURRENT)
        self.assertEqual(mapping['daily_run'], daily, 'recovery remains independently visible')
        self.assertEqual(self.files(), before)
        self.assertNotEqual(reference['status'], 'CONSUMED', 'US07 cannot satisfy dynamic US08')
        self.assertEqual(identities, [])

    def test_valid_empty_does_not_bypass_session_gate(self):
        self.save_daily(status='VALID_EMPTY')
        _, reference, identities = self.reference(CURRENT)
        self.assertNotEqual(reference['status'], 'CONSUMED')
        self.assertEqual(identities, [])

    def test_recovery_generated_after_historical_cutoff_keeps_original_rejection(self):
        daily = self.save_daily()
        mapping, reference, identities = self.reference(PREOPEN)
        self.assertEqual(mapping['daily_run'], daily)
        self.assertEqual(reference['status'], 'NOT_CONSUMED_AFTER_CUTOFF')
        self.assertEqual(reference['reason'], 'DAILY_MAPPING_NOT_AVAILABLE_AT_PLAN_CUTOFF')
        self.assertEqual(identities, [])

    def test_actual_workspace_keeps_recovery_separate_and_get_has_no_writes(self):
        daily = self.save_daily()
        before = self.files()
        value = self.w.get_workspace(self.service, DAY, view='dynamic', now=CURRENT)
        self.assertEqual(self.files(), before)
        self.assertEqual(value['us_mapping_research']['daily_run'], daily)
        self.assertEqual(value['us_market_attention']['expected_us_session'], '20261008')
        self.assertEqual(value['us_market_attention']['status'], 'INPUT_MISSING')
        self.assertEqual([r['channel'] for r in value['daily_channels']['channels']],
                         ['ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'])
        self.assertEqual(value['date_bindings'], dict(
            selection_date=DAY, announcement_date='20261007', plan_date=DAY))
        self.assertNotEqual(value['owner_chain']['us_mapping_daily_plan_reference']['status'], 'CONSUMED')

    def test_actual_saved_plan_independent_store_same_attempt_rejects_old_session(self):
        daily = self.save_daily()
        result = self.w.refresh_workspace_plan(self.service, DAY, now=CURRENT)
        independent = self.store_type(self.service.store.root)
        saved = self.w._read_plan(independent, DAY)
        attempt = self.w.verified_plan_attempt(independent, saved)
        self.assertEqual(saved['run_id'], result['plan_product']['run_id'])
        self.assertEqual(attempt['run_id'], saved['run_id'])
        self.assertIn(attempt['state'], {'PARTIAL', 'SUCCEEDED', 'SUCCEEDED_EMPTY'})
        self.assertEqual(saved['workspace']['us_mapping_research']['daily_run'], daily)
        self.assertNotEqual(saved['workspace']['owner_chain']['us_mapping_daily_plan_reference']['status'], 'CONSUMED')

    def test_rejected_daily_artifact_does_not_change_valid_plan_input_identity(self):
        self.save_daily(generated='2026-10-09T08:59:00+08:00')
        first = self.w.get_workspace(self.service, DAY, include_saved=False, now=CURRENT)
        self.save_daily(generated='2026-10-09T09:00:00+08:00')
        second = self.w.get_workspace(self.service, DAY, include_saved=False, now=CURRENT)
        self.assertNotEqual(first['us_mapping_research']['daily_run']['artifact_sha256'],
                            second['us_mapping_research']['daily_run']['artifact_sha256'])
        self.assertEqual(first['input_identity'], second['input_identity'],
                         'a rejected old-session daily SHA must not enter plan identity')

    def test_independent_readback_rejects_wrong_run_terminal_attempt(self):
        self.save_daily()
        self.w.refresh_workspace_plan(self.service, DAY, now=CURRENT)
        independent = self.store_type(self.service.store.root)
        saved = self.w._read_plan(independent, DAY)
        path = independent.root / 'workspace_plan_runs' / DAY / (saved['run_id'] + '.json')
        attempt = independent._read(path)
        attempt['run_id'] = '2' * 32
        independent._write_atomic(path, self.w.seal_attempt(attempt))
        with self.assertRaises(ValueError):
            self.w.verified_plan_attempt(independent, saved)


if __name__ == '__main__':
    unittest.main()
