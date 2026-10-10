"""Offline regression using actual pinned/supplied modules and isolated sealed products.

WORKSPACE_SOURCE_ROOT selects the pristine assembled baseline or candidate.
Recovered fixed-tree dependencies are imported from recovery_sources/dependencies.
No AST extraction, live owner roots, API calls, data capture, or deployment.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(os.environ.get('WORKSPACE_SOURCE_ROOT', BASE / 'candidate')).resolve()
DEPENDENCY_ROOT = Path(os.environ.get('WORKSPACE_DEPENDENCY_ROOT', BASE / 'recovery_sources/dependencies')).resolve()
sys.path[:0] = [str(SOURCE_ROOT), str(DEPENDENCY_ROOT)]
from v4.manager_research import workspace as W
from v4.manager_research.workspace_projection import build_workspace, digest, FLAGS
from v4.manager_research.existing_materials import project_archive

DATE = '20261009'
CUTOFF = '2026-10-10T09:00:00+08:00'
SCHEMA = 'v4.manager_research.input_identity.v2'



def material():
    return dict(material_id='isolated-material', source_kind='zsxq', archive_date='20261008',
        available_at='2026-10-08T17:00:00+08:00', content='Synthetic research material, not market data.', verification='OWNER_VERIFIED', title='Synthetic material', themes=[],
        source_row={'title': 'Synthetic source', 'body': 'Stable semantic body'},
        source_refs=[dict(source_root='/ISOLATED/research', source_date='20261008',
            source_id='V35_RESEARCH_DATA_ROOT', status='VERIFIED', slot='', mode='LIVE',
            manifest_path='manifest.json', recommendation_status='RESEARCH_ONLY',
            write_policy='read_only', production_allowed=False, buy_gate_updated=False, orders_sent=False,
            payload_path='research/archives/20261008.json',
            manifest_entry_sha256='a' * 64, payload_sha256='a' * 64,
            receipt_path='receipts/research/archives/20261008.json', receipt_sha256='b' * 64,
            manifest_sha256='c' * 64)])


def relation_input(rows):
    return W._research_relation_material_input(pre_connect_cards=[], post_connect_cards=[], relation_cards=[],
        connect_scope=dict(target_trade_date=DATE, identity='d' * 64, status='CANNOT_CONFIRM',
            gaps=['TARGET_DATE_HK_CONNECT_AUTHORITY_UNVERIFIED']), connect_rejections=[],
        material_discovery=dict(status='READY', gaps=[]), selection_materials=rows,
        existing={'gaps': []}, announcement_inputs={'gaps': []})


def projection(rows):
    identity = relation_input(rows)['input_identity']
    component = dict(sha256=identity, sources=deepcopy(rows[0]['source_refs']))
    return dict(target_trade_date=DATE, input_identity=identity,
        input_identity_schema=SCHEMA, input_identity_components={'materials': component},
        semantic_version='isolated-owner-contract',
        date_bindings=dict(plan_date=DATE, selection_date=DATE, announcement_date='20261008'), plan_context={'research_cutoff': CUTOFF},
        materials=deepcopy(rows), gaps=['SYNTHETIC_INCOMPLETE_INPUT'], stocks=[],
        lanes=[], daily_channels={}, **FLAGS)


class Store:
    def __init__(self):
        self.root = Path('/ISOLATED/manager')
        self.rows = {}
        self.read_paths = []
        self.write_count = 0

    def _read(self, path):
        self.read_paths.append(str(path))
        return deepcopy(self.rows.get(str(path)))

    def put(self, relative, value):
        self.rows[str(self.root / relative)] = deepcopy(value)


def seal_plan(store, value):
    product = dict(schema_version=W.PLAN_SCHEMA, target_trade_date=DATE, run_id='1' * 32,
        generated_at=CUTOFF, owner='ManagerResearchJobService.refresh_workspace_plan',
        execution_kind='MANUAL_REFRESH', input_identity=value['input_identity'],
        workspace=deepcopy(value), **FLAGS)
    product['sha256'] = digest(product)
    store.put(f'workspace_plans/{DATE}/latest.json', product)
    store.put(f'workspace_plans/{DATE}/{product["run_id"]}.json', product)
    attempt = W.seal_attempt(dict(schema_version=W.ATTEMPT_SCHEMA, target_trade_date=DATE,
        run_id=product['run_id'], owner=product['owner'], execution_kind='MANUAL_REFRESH',
        state='PARTIAL', started_at='2026-10-10T08:59:59+08:00', finished_at=CUTOFF,
        input_identity=value['input_identity'], failure_reasons=['SYNTHETIC_INCOMPLETE_INPUT'], **FLAGS))
    store.put(f'workspace_plan_runs/{DATE}/latest.json', attempt)
    store.put(f'workspace_plan_runs/{DATE}/{product["run_id"]}.json', attempt)
    return product


class SemanticIdentityRegression(unittest.TestCase):
    def test_unconsumed_registry_entry_change_keeps_actual_projection_identity(self):
        rows = [material()]
        consumed_path = rows[0]['source_refs'][0]['payload_path']
        manifest = {consumed_path: rows[0]['source_refs'][0]['payload_sha256'],
            'research/archives/20260901.json': 'd' * 64}
        before_global = digest(manifest)
        rows[0]['source_refs'][0]['manifest_sha256'] = before_global
        before = build_workspace(DATE, catalyst={}, materials=rows, stage=None, close=None)
        changed_manifest = deepcopy(manifest)
        changed_manifest['research/archives/20260901.json'] = 'e' * 64
        self.assertEqual(manifest[consumed_path], changed_manifest[consumed_path])
        after_global = digest(changed_manifest)
        self.assertNotEqual(before_global, after_global)
        after_rows = deepcopy(rows)
        after_rows[0]['source_refs'][0]['manifest_sha256'] = after_global
        after = build_workspace(DATE, catalyst={}, materials=after_rows, stage=None, close=None)
        self.assertEqual(before['input_identity'], after['input_identity'])
        self.assertEqual(before['materials'][0]['source_refs'][0]['manifest_sha256'], before_global)
        self.assertEqual(after['materials'][0]['source_refs'][0]['manifest_sha256'], after_global)

    def test_unproven_binding_and_business_content_do_not_gain_exemption(self):
        for field, value in [('source_id', 'STAGE_OWNER'), ('status', 'CANNOT_CONFIRM'),
                ('receipt_sha256', ''), ('source_date', 'not-a-date'),
                ('manifest_path', 'hkconnect/manifest.json'), ('production_allowed', True),
                ('payload_path', '../unbound.json')]:
            with self.subTest(field=field):
                before = material()
                before['source_refs'][0][field] = value
                after = deepcopy(before)
                after['source_refs'][0]['manifest_sha256'] = 'e' * 64
                self.assertNotEqual(relation_input([before])['input_identity'], relation_input([after])['input_identity'])
        before = material()
        before['source_row']['manifest_sha256'] = 'c' * 64
        before['source_row']['source_refs'] = deepcopy(before['source_refs'])
        after = deepcopy(before)
        after['source_row']['source_refs'][0]['manifest_sha256'] = 'e' * 64
        self.assertNotEqual(relation_input([before])['input_identity'], relation_input([after])['input_identity'])
        after = deepcopy(before)
        after['source_row']['manifest_sha256'] = 'e' * 64
        self.assertNotEqual(relation_input([before])['input_identity'], relation_input([after])['input_identity'])

    def test_archive_projection_keeps_exact_original_binding_and_source_row(self):
        row = dict(article_id='synthetic-a', source_title='Synthetic archive row', available_at=CUTOFF,
            source_refs=[{'manifest_sha256': 'business-content'}])
        binding = material()['source_refs'][0]
        before = deepcopy(binding)
        rows, _ = project_archive(dict(archive_date='20261008', articles=[row]), binding, '20261008')
        self.assertEqual(rows[0]['source_refs'], [before])
        self.assertEqual(rows[0]['source_row'], row)
        self.assertEqual(binding, before)

    def test_unrelated_registry_change_keeps_consumed_material_identity(self):
        before = material()
        after = deepcopy(before)
        after['source_refs'][0]['manifest_sha256'] = 'e' * 64
        self.assertEqual(relation_input([before])['input_identity'], relation_input([after])['input_identity'])
        self.assertNotEqual(before['source_refs'][0]['manifest_sha256'], after['source_refs'][0]['manifest_sha256'])

    def test_manifest_only_readback_remains_current_same_run_product_date(self):
        rows = [material()]
        store = Store()
        saved = seal_plan(store, projection(rows))
        immutable_before = deepcopy(store.rows)
        for global_sha in ('e' * 64, 'f' * 64):
            rows[0]['source_refs'][0]['manifest_sha256'] = global_sha
            got = W._readback_plan(store, DATE, projection(rows), read_at=CUTOFF)
            self.assertEqual(got['plan_product']['status'], 'CURRENT')
            self.assertTrue(got['plan_product']['consumed'])
            self.assertEqual(got['plan_product']['run_id'], saved['run_id'])
            self.assertEqual(got['plan_product']['sha256'], saved['sha256'])
            self.assertEqual(got['target_trade_date'], DATE)
            self.assertEqual(got['date_bindings']['announcement_date'], '20261008')
            for key, expected in FLAGS.items():
                self.assertIs(got[key], expected)
        self.assertEqual(store.rows, immutable_before)
        self.assertEqual(store.write_count, 0)

    def test_consumed_payload_receipt_entry_date_root_and_path_remain_sensitive(self):
        base = material()
        identity = relation_input([base])['input_identity']
        changes = dict(payload_sha256='e' * 64, receipt_sha256='f' * 64,
            manifest_entry_sha256='9' * 64, source_date='20261007',
            source_root='/ISOLATED/other', payload_path='research/archives/20261007.json',
            receipt_path='receipts/research/archives/20261007.json', source_id='OTHER_OWNER')
        for key, value in changes.items():
            with self.subTest(field=key):
                after = deepcopy(base)
                after['source_refs'][0][key] = value
                self.assertNotEqual(identity, relation_input([after])['input_identity'])

    def test_semantic_availability_and_content_remain_sensitive(self):
        base = material()
        identity = relation_input([base])['input_identity']
        for key, value in [('available_at', None), ('content', 'Changed content'),
                ('source_row', {'title': 'Changed original source'})]:
            with self.subTest(field=key):
                after = deepcopy(base)
                after[key] = value
                self.assertNotEqual(identity, relation_input([after])['input_identity'])

    def test_genuine_change_is_stale_with_source_backed_component_diagnostics(self):
        rows = [material()]
        store = Store()
        saved = seal_plan(store, projection(rows))
        rows[0]['source_refs'][0]['receipt_sha256'] = 'f' * 64
        got = W._readback_plan(store, DATE, projection(rows), read_at=CUTOFF)
        self.assertEqual(got['plan_product']['status'], 'STALE_INPUTS_CHANGED')
        self.assertFalse(got['plan_product']['consumed'])
        diagnostics = got['plan_product'].get('input_identity_diagnostics')
        self.assertIsInstance(diagnostics, dict)
        self.assertEqual(diagnostics['status'], 'CHANGED')
        changed = {row['component']: row for row in diagnostics['changed_components']}
        self.assertIn('materials', changed)
        self.assertEqual(changed['materials']['saved_sources'][0]['receipt_sha256'], 'b' * 64)
        self.assertEqual(changed['materials']['current_sources'][0]['receipt_sha256'], 'f' * 64)
        self.assertEqual(diagnostics['saved_input_identity'], saved['input_identity'])

    def test_legacy_plan_requires_owner_refresh_even_if_hash_is_copied(self):
        current = projection([material()])
        old = deepcopy(current)
        old.pop('input_identity_schema')
        old.pop('input_identity_components')
        store = Store()
        seal_plan(store, old)
        got = W._readback_plan(store, DATE, current, read_at=CUTOFF)
        self.assertFalse(got['plan_product']['consumed'])
        self.assertEqual(got['plan_product']['status'], 'STALE_INPUTS_CHANGED')
        self.assertEqual(got['plan_product']['input_identity_diagnostics']['reason'],
            'SAVED_IDENTITY_COMPONENTS_UNAVAILABLE_OWNER_REFRESH_REQUIRED')

    def test_date_and_semantic_version_guards_still_reject(self):
        for key in ('date_bindings', 'semantic_version'):
            with self.subTest(field=key):
                store = Store()
                saved = projection([material()])
                seal_plan(store, saved)
                current = deepcopy(saved)
                if key == 'date_bindings':
                    current[key]['announcement_date'] = '20261007'
                else:
                    current[key] = 'changed-semantics'
                got = W._readback_plan(store, DATE, current, read_at=CUTOFF)
                self.assertEqual(got['plan_product']['status'], 'STALE_INPUTS_CHANGED')
                self.assertFalse(got['plan_product']['consumed'])
                diagnostics = got['plan_product'].get('input_identity_diagnostics', {})
                self.assertIn(key, {row['component'] for row in diagnostics.get('changed_components', [])})

    def test_earlier_read_cutoff_cannot_consume_later_plan(self):
        store = Store()
        saved = projection([material()])
        seal_plan(store, saved)
        current = deepcopy(saved)
        current['plan_context']['research_cutoff'] = '2026-10-10T08:59:00+08:00'
        got = W._readback_plan(store, DATE, current, read_at=CUTOFF)
        self.assertEqual(got['plan_product']['status'], 'PLAN_AFTER_READ_CUTOFF')
        self.assertFalse(got['plan_product']['consumed'])
        diagnostics = got['plan_product'].get('input_identity_diagnostics', {})
        self.assertIn('research_cutoff', {row['component'] for row in diagnostics.get('changed_components', [])})

    def test_product_hash_and_research_only_flags_still_fail_closed(self):
        for key in ('sha256', 'production_allowed', 'buy_gate_updated', 'orders_sent', 'RESEARCH_ONLY'):
            with self.subTest(field=key):
                store = Store()
                current = projection([material()])
                saved = seal_plan(store, current)
                saved[key] = '0' * 64 if key == 'sha256' else not FLAGS[key]
                if key != 'sha256':
                    saved['sha256'] = digest({k: v for k, v in saved.items() if k != 'sha256'})
                store.put(f'workspace_plans/{DATE}/latest.json', saved)
                got = W._readback_plan(store, DATE, current, read_at=CUTOFF)
                self.assertEqual(got['plan_product']['status'], 'READBACK_FAILED')
                self.assertIsNot(got['plan_product'].get('consumed'), True)

    def test_missing_exact_owner_attempt_still_prevents_consumption(self):
        store = Store()
        current = projection([material()])
        saved = seal_plan(store, current)
        store.rows.pop(str(store.root / f'workspace_plan_runs/{DATE}/{saved["run_id"]}.json'))
        got = W._readback_plan(store, DATE, current, read_at=CUTOFF)
        self.assertEqual(got['plan_product']['status'], 'OWNER_ATTEMPT_UNVERIFIED')
        self.assertFalse(got['plan_product']['consumed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
