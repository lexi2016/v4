"""Real _compute_workspace and readback; synthetic values at owner-read boundaries.

The original projection, Connect gate, event lane, attention, semantic identity,
and sealed saved-product/owner-attempt comparison run as actual module code.
Only read-only external owner-return boundaries are injected; no owner is run.
"""
from contextlib import ExitStack
from copy import deepcopy
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from test_plan_semantic_identity import W, FLAGS, DATE, CUTOFF, Store, material, seal_plan, digest
from test_research_attention_identity import card
from v4.manager_research import connect_selection

CONTEXT = dict(plan_trade_date=DATE, market_session='20261008', research_cutoff=CUTOFF,
    announcement_publication_date='2026-10-08', focus_window_start='2026-10-07T16:00:00+08:00')
BINDINGS = dict(plan_date=DATE, selection_date=DATE, announcement_date='20261008')


def compute(rows, store, *, announcement_identity='7' * 64, mapping_ids=()):
    empty_owner = lambda _: dict(status='CANNOT_CONFIRM', target_trade_date=DATE, cannot_confirm=[])
    service = SimpleNamespace(store=store, observation_reader=empty_owner,
        _close_observation_reader=empty_owner, _catalyst_data_root='/ISOLATED/no-read',
        get_catalyst_observations=lambda _: dict(status='READY_EMPTY', cards=[], target_trade_date=DATE))
    selected = deepcopy(card())
    selected['source_refs'] = deepcopy(rows[0]['source_refs'])
    selected['available_at'] = rows[0]['available_at']
    scope = dict(status='CANNOT_CONFIRM', target_trade_date=DATE, identity='8' * 64,
        source={}, codes=[], gaps=['TARGET_DATE_HK_CONNECT_AUTHORITY_UNVERIFIED'])
    review = dict(status='NOT_RUN', official_documents=[], gaps=['ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED'])
    announcement_inputs = dict(status='CANNOT_CONFIRM', input_identity=announcement_identity,
        materials=[], captures=[], rejections=[], gaps=['ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED'])
    screen = dict(status='CANNOT_CONFIRM', input_identity='9' * 64, cards=[], coverage={},
        gaps=['SYNTHETIC_SCREEN_INPUT_INCOMPLETE'])
    mapping = dict(daily_run=dict(status='VALID_EMPTY', target_trade_date=DATE, run_id='2' * 32,
        artifact_sha256=mapping_ids[0] if mapping_ids else None, generated_at=CUTOFF,
        matches=[], coverage={'reviewed_us_symbol_count': 4, 'full_market_coverage': False}, **FLAGS))
    with ExitStack() as stack:
        owner_returns = {
            '_read_close_recapture_inputs': ({}, {}),
            '_materials': dict(materials=deepcopy(rows), input_bindings=deepcopy(rows[0]['source_refs']),
                gaps=[], coverage={}),
            '_discovery': dict(cards=[], gaps=[], coverage={}),
            'read_material_discovery': dict(cards=[selected], rejected_relations=[], status='READY', coverage={}, gaps=[]),
            'read_plan_quotes': dict(verified=False, quotes={}, gaps=[]),
            'read_rebound_screen': screen,
            '_previous_observation': (None, 'SYNTHETIC_PRIOR_OBSERVATION_UNAVAILABLE'),
            '_stage_attempt': (None, ['STAGE_TARGET_EXECUTION_RECEIPT_NOT_FOUND']),
            '_project_us_market_attention': dict(status='CANNOT_CONFIRM', source_identity=None, gaps=[]),
            '_daily_mapping_plan_reference': (mapping, dict(status='CONSUMED' if mapping_ids else 'NOT_CONSUMED',
                target_trade_date=DATE, run_id='2' * 32, artifact_sha256=mapping_ids[0] if mapping_ids else None), list(mapping_ids)),
        }
        for name, value in owner_returns.items():
            stack.enter_context(patch.object(W, name, side_effect=lambda *a, _v=value, **kw: deepcopy(_v)))
        # The source owner's transitively imported storage modules are omitted
        # from the ZIP. Replace only this original read-only owner boundary;
        # no projection/identity/guard function is replaced.
        announcements = ModuleType('v4.manager_research.workspace_announcements')
        announcements.read = lambda *a, **kw: deepcopy(review)
        announcements.read_selection_inputs = lambda *a, **kw: deepcopy(announcement_inputs)
        stack.enter_context(patch.dict('sys.modules', {announcements.__name__: announcements}))
        stack.enter_context(patch.object(connect_selection, 'read_scope', return_value=scope))
        result = W._compute_workspace(service, DATE, include_saved=False, context=CONTEXT)
    # Same caller boundary as get_workspace: query dates bind before readback.
    result['date_bindings'] = deepcopy(BINDINGS)
    return result


class WorkspaceIdentityIntegration(unittest.TestCase):
    def test_entire_identity_chain_preserves_same_saved_run_on_registry_only_change(self):
        rows = [material()]
        store = Store()
        initial = compute(rows, store)
        self.assertEqual(len(initial['research_attention']['cards']), 1)
        saved = seal_plan(store, initial)
        snapshot = deepcopy(store.rows)
        for global_sha in ('d' * 64, 'e' * 64):
            rows[0]['source_refs'][0]['manifest_sha256'] = global_sha
            current = compute(rows, store)
            self.assertEqual(initial['input_identity'], current['input_identity'])
            got = W._readback_plan(store, DATE, current, read_at=CUTOFF)
            self.assertEqual(got['plan_product']['status'], 'CURRENT')
            self.assertTrue(got['plan_product']['consumed'])
            self.assertEqual(got['plan_product']['run_id'], saved['run_id'])
            self.assertEqual(got['plan_product']['sha256'], saved['sha256'])
            self.assertEqual(got['daily_channels']['date_bindings'], BINDINGS)
            self.assertEqual({row['channel'] for row in got['daily_channels']['channels']},
                {'ANNOUNCEMENT', 'HK_CONNECT', 'OVERSOLD'})
            for row in got['daily_channels']['channels']:
                self.assertEqual(row['target_trade_date'], DATE)
                self.assertEqual(row['announcement_date'], '20261008')
                for key, expected in FLAGS.items():
                    self.assertIs(row[key], expected)
        self.assertEqual(store.rows, snapshot)

    def test_real_leaf_changes_explain_staleness_through_actual_outer_components(self):
        for change in ('payload_sha256', 'receipt_sha256', 'available_at'):
            with self.subTest(change=change):
                rows = [material()]
                store = Store()
                saved = seal_plan(store, compute(rows, store))
                if change == 'available_at':
                    rows[0][change] = '2026-10-08T18:00:00+08:00'
                else:
                    rows[0]['source_refs'][0][change] = 'f' * 64
                got = W._readback_plan(store, DATE, compute(rows, store), read_at=CUTOFF)
                self.assertEqual(got['plan_product']['status'], 'STALE_INPUTS_CHANGED')
                self.assertFalse(got['plan_product']['consumed'])
                self.assertEqual(got['plan_product']['run_id'], saved['run_id'])
                diagnostics = got['plan_product'].get('input_identity_diagnostics')
                self.assertIsInstance(diagnostics, dict)
                changes = diagnostics['changed_components']
                materials = next(row for row in changes if row['component'] == 'projection.materials')
                self.assertEqual(materials['saved_sources'][0]['payload_path'], 'research/archives/20261008.json')
                self.assertNotEqual(materials['saved_sha256'], materials['current_sha256'])

    def test_independent_announcement_and_daily_mapping_identity_extensions_still_invalidate(self):
        rows = [material()]
        for field, override, component in (
                ('announcement', {'announcement_identity': 'a' * 64}, 'announcement_inputs'),
                ('daily_mapping', {'mapping_ids': ['b' * 64]}, 'us_mapping_daily_reference')):
            with self.subTest(extension=field):
                store = Store()
                seal_plan(store, compute(rows, store))
                got = W._readback_plan(store, DATE, compute(rows, store, **override), read_at=CUTOFF)
                self.assertEqual(got['plan_product']['status'], 'STALE_INPUTS_CHANGED')
                self.assertFalse(got['plan_product']['consumed'])
                diagnostics = got['plan_product'].get('input_identity_diagnostics')
                self.assertIsInstance(diagnostics, dict)
                changes = diagnostics['changed_components']
                self.assertIn(component, {row['component'] for row in changes})


if __name__ == '__main__':
    unittest.main(verbosity=2)
