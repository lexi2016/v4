"""Existing scheduled reuse must obey the same saved identity compatibility.

Only in-memory sealed products are used; native window resolution is injected.
No scheduler, service, owner capture, or external state is started or changed.
"""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_plan_semantic_identity import W, DATE, Store, FLAGS, digest, build_workspace
from v4.manager_research import workspace_plan_autorun as autorun
from v4.manager_research.workspace_projection import HK

BEFORE = '2026-10-09T08:00:00+08:00'
NOW = datetime(2026, 10, 9, 8, 5, tzinfo=HK)
DEADLINE = datetime(2026, 10, 9, 9, 25, tzinfo=HK)


class MemoryStore(Store):
    def _transaction(self, *args):
        return nullcontext()

    def _write_atomic(self, path, value):
        self.write_count += 1
        self.rows[str(path)] = deepcopy(value)


def prepared():
    value = build_workspace(DATE, catalyst={}, materials=[], stage=None, close=None)
    value['date_bindings'] = dict(plan_date=DATE, selection_date=DATE, announcement_date='20261008')
    value['plan_context']['research_cutoff'] = BEFORE
    value['existing_material_coverage'] = {}
    return value


def save(store, workspace, kind, *, legacy=False):
    workspace = deepcopy(workspace)
    if legacy:
        workspace.pop('input_identity_schema', None)
        workspace.pop('input_identity_components', None)
    value = dict(schema_version=W.PLAN_SCHEMA, target_trade_date=DATE, run_id='3' * 32,
        generated_at=BEFORE, owner='ManagerResearchJobService.refresh_workspace_plan',
        execution_kind=kind, input_identity=workspace['input_identity'], workspace=workspace, **FLAGS)
    value['sha256'] = digest(value)
    attempt = W.seal_attempt(dict(schema_version=W.ATTEMPT_SCHEMA, target_trade_date=DATE,
        run_id=value['run_id'], owner=value['owner'], execution_kind=kind, state='PARTIAL',
        started_at='2026-10-09T07:59:00+08:00', finished_at=BEFORE,
        input_identity=value['input_identity'], failure_reasons=['SYNTHETIC_INCOMPLETE_INPUT'], **FLAGS))
    for suffix in ('latest', value['run_id']):
        store.put(f'workspace_plans/{DATE}/{suffix}.json', value)
        store.put(f'workspace_plan_runs/{DATE}/{suffix}.json', attempt)
    return value


def refresh(store, current, kind):
    with patch.object(autorun, 'morning_window', return_value=(NOW.replace(hour=7), DEADLINE)), \
         patch.object(autorun, 'preopen_window', return_value=(NOW.replace(hour=7), DEADLINE)), \
         patch.object(W, 'get_workspace', return_value=deepcopy(current)), \
         patch.object(W, '_now', return_value=NOW.isoformat()):
        return W.refresh_workspace_plan(SimpleNamespace(store=store), DATE,
            execution_kind=kind, now=NOW, deadline=DEADLINE)


class ScheduledIdentityCompatibility(unittest.TestCase):
    def test_both_existing_scheduled_reuse_entries_reject_legacy_plan(self):
        for kind in ('SCHEDULED_PREOPEN', 'SCHEDULED_MORNING'):
            with self.subTest(execution_kind=kind):
                store = MemoryStore()
                current = prepared()
                old = save(store, current, kind, legacy=True)
                got = refresh(store, current, kind)
                self.assertFalse(got['plan_product'].get('consumed') is True
                    and got['plan_product'].get('run_id') == old['run_id'],
                    'The saved legacy run must not be promoted to consumed.')
                self.assertEqual(store._read(store.root / f'workspace_plans/{DATE}/{old["run_id"]}.json'), old)

    def test_both_existing_scheduled_reuse_entries_keep_compatible_v2_plan(self):
        for kind in ('SCHEDULED_PREOPEN', 'SCHEDULED_MORNING'):
            with self.subTest(execution_kind=kind):
                store = MemoryStore()
                current = prepared()
                saved = save(store, current, kind)
                before = deepcopy(store.rows)
                got = refresh(store, current, kind)
                self.assertEqual(got['plan_product']['status'], 'ALREADY_MATERIALIZED')
                self.assertTrue(got['plan_product']['consumed'])
                self.assertEqual(got['plan_product']['run_id'], saved['run_id'])
                self.assertEqual(got['plan_product']['sha256'], saved['sha256'])
                diagnostics = got['plan_product'].get('input_identity_diagnostics')
                self.assertIsInstance(diagnostics, dict)
                self.assertEqual(diagnostics['status'], 'MATCH')
                self.assertEqual(store.rows, before)
                self.assertEqual(store.write_count, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
