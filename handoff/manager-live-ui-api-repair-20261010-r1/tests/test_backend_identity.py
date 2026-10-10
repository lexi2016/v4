"""Offline regression tests for the fixed Manager semantic identity boundary.

Fixtures are isolated research materials. They are not receipts for the live
20261009 run. The real projection and plan/source guards are exercised through
the test-support overlay documented by the root repair worker.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v4.manager_research.workspace_projection import build_workspace, digest


DATE = '20261009'
SOURCE_DATE = '20261007'
OLD_MANIFEST = 'c8a8fc7f1fe654d7f700c960ead60fce1dd075c9999a3ad1b98932dcc180dcc4'
NEW_MANIFEST = '864e1f6d789e9a8a9b2614ac2534f6e4cdce55ccc46242fefba7203f1fed6e31'
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def binding() -> dict:
    return dict(
        source_id='V35_RESEARCH_DATA_ROOT', source_root='/NOT_LIVE/backend_identity/source',
        ledger_root='/NOT_LIVE/backend_identity/dispatcher',
        binding_policy='EXPLICIT_RESEARCH_DATA_ROOT_OR_SERVER_DATA_ROOT',
        write_policy='read_only', recommendation_status='RESEARCH_ONLY',
        status='VERIFIED', source_date=SOURCE_DATE, slot='', mode='LIVE',
        payload_path=f'research/archives/{SOURCE_DATE}.json', payload_sha256='a' * 64,
        receipt_path=f'receipts/research/archives/{SOURCE_DATE}.json', receipt_sha256='b' * 64,
        manifest_path='manifest.json', manifest_sha256=OLD_MANIFEST,
        production_allowed=False, buy_gate_updated=False, orders_sent=False,
    )


def material() -> dict:
    return dict(
        material_id='1' * 64, original_article_id='fixture-article',
        title='研究材料 fixture', themes=['AI_APPLICATION'], claim_type='RESEARCH_OPINION',
        source_kind='zsxq', source_market='UNKNOWN', source_url=None,
        published_at=None, published_date=None, retrieved_at=None, available_at=None,
        collected_at=None, first_seen_at=None, archive_recorded_at=None,
        archive_date=SOURCE_DATE, verification='OWNER_VERIFIED', source_refs=[binding()],
        source_row=dict(article_id='fixture-article', source_title='研究材料 fixture',
                        content='Original research content remains identity-sensitive.'),
        fresh_catalyst_eligible=False, identity_status='HK_IDENTITY_AND_CONNECT_NOT_VERIFIED',
    )


def projection(rows: list[dict]) -> dict:
    return build_workspace(DATE, catalyst={}, stage=None, close=None, materials=rows)


class ProjectionIdentityTests(unittest.TestCase):
    def test_new_projection_records_versioned_bounded_component_evidence(self):
        value = projection([material()])
        evidence = value.get('input_identity_components')
        self.assertIsInstance(evidence, dict)
        self.assertEqual(evidence['schema_version'], 'v4.manager_research.input_identity_components.v1')
        self.assertEqual(value.get('input_identity_version'), evidence['identity_version'])
        self.assertEqual(evidence['identity_version'], 'CONSUMED_RESEARCH_ARTIFACTS_V1')
        self.assertIn('projection.materials', evidence['digests'])
        self.assertLessEqual(len(evidence['digests']), 32)
        changed = [material()]
        changed[0]['source_row']['content'] += ' changed'
        after = projection(changed)['input_identity_components']['digests']
        self.assertEqual([key for key in after if after[key] != evidence['digests'][key]], ['projection.materials'])

    def test_only_unconsumed_registry_change_preserves_projection_identity(self):
        rows = [material()]
        changed = deepcopy(rows)
        changed[0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
        before = projection(rows)
        after = projection(changed)
        self.assertEqual(before['input_identity'], after['input_identity'])
        self.assertEqual(after['materials'][0]['source_refs'][0]['manifest_sha256'], NEW_MANIFEST)
        self.assertEqual(rows[0]['source_refs'][0]['manifest_sha256'], OLD_MANIFEST)
        self.assertEqual(after['materials'][0]['source_row'], rows[0]['source_row'])
        for key, expected in FLAGS.items():
            self.assertIs(after[key], expected)

    def test_consumed_payload_and_receipt_changes_invalidate(self):
        rows = [material()]
        original = projection(rows)['input_identity']
        for field in ('payload_sha256', 'receipt_sha256'):
            with self.subTest(field=field):
                changed = deepcopy(rows)
                changed[0]['source_refs'][0][field] = 'd' * 64
                self.assertNotEqual(original, projection(changed)['input_identity'])

    def test_consumed_source_date_root_and_paths_remain_sensitive(self):
        rows = [material()]
        original = projection(rows)['input_identity']
        changes = dict(source_date='20261008', source_root='/NOT_LIVE/other/source',
                       payload_path='research/archives/20261008.json',
                       receipt_path='receipts/research/archives/20261008.json')
        for field, replacement in changes.items():
            with self.subTest(field=field):
                changed = deepcopy(rows)
                changed[0]['source_refs'][0][field] = replacement
                self.assertNotEqual(original, projection(changed)['input_identity'])

    def test_semantic_available_at_and_content_remain_sensitive(self):
        rows = [material()]
        original = projection(rows)['input_identity']
        changed = deepcopy(rows)
        changed[0]['available_at'] = '2026-10-07T12:00:00+08:00'
        self.assertNotEqual(original, projection(changed)['input_identity'])
        changed = deepcopy(rows)
        changed[0]['source_row']['content'] += ' A material fact changed.'
        self.assertNotEqual(original, projection(changed)['input_identity'])

    def test_binding_shaped_source_content_is_never_normalized(self):
        rows = [material()]
        rows[0]['source_row']['quoted_binding'] = binding()
        rows[0]['source_row']['source_refs'] = [binding()]
        original = projection(rows)['input_identity']
        for key in ('quoted_binding', 'source_refs'):
            changed = deepcopy(rows)
            quoted = changed[0]['source_row'][key]
            ref = quoted[0] if isinstance(quoted, list) else quoted
            ref['manifest_sha256'] = NEW_MANIFEST
            with self.subTest(key=key):
                self.assertNotEqual(original, projection(changed)['input_identity'])

    def test_incomplete_or_invalid_binding_does_not_gain_registry_compatibility(self):
        changes = [
            ('status', 'CANNOT_CONFIRM'), ('source_id', 'OTHER_OWNER'),
            ('source_root', ''), ('source_date', '20269999'), ('mode', 'UNKNOWN'), ('mode', []),
            ('payload_path', '../outside.json'), ('payload_sha256', 'short'),
            ('receipt_path', ''), ('receipt_sha256', ''), ('manifest_path', 'other.json'),
            ('production_allowed', True), ('RESEARCH_ONLY', False),
            ('manifest_entry_sha256', 'e' * 64),
        ]
        for field, replacement in changes:
            with self.subTest(field=field):
                rows = [material()]
                rows[0]['source_refs'][0][field] = replacement
                changed = deepcopy(rows)
                changed[0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
                self.assertNotEqual(projection(rows)['input_identity'], projection(changed)['input_identity'])

    def test_other_manifest_scopes_remain_semantic(self):
        rows = [material()]
        rows[0]['source_refs'].append(dict(owner='SECURITY_MASTER', manifest_sha256=OLD_MANIFEST,
                                         artifact_sha256='7' * 64))
        changed = deepcopy(rows)
        changed[0]['source_refs'][1]['manifest_sha256'] = NEW_MANIFEST
        self.assertNotEqual(projection(rows)['input_identity'], projection(changed)['input_identity'])

    def test_generic_digest_still_seals_full_bytes(self):
        source = binding()
        changed = {**source, 'manifest_sha256': NEW_MANIFEST}
        self.assertNotEqual(digest(source), digest(changed))


def relation_input(rows: list[dict], cards: list[dict] | None = None) -> dict:
    from v4.manager_research.workspace import _research_relation_material_input
    return _research_relation_material_input(
        pre_connect_cards=[], post_connect_cards=[], relation_cards=cards or [],
        connect_scope=dict(target_trade_date=DATE, identity='4' * 64, status='OWNER_VERIFIED', gaps=[]),
        connect_rejections=[], material_discovery=dict(status='READY', gaps=[]),
        selection_materials=rows, existing=dict(gaps=[]), announcement_inputs=dict(gaps=[]),
    )


class RelationIdentityTests(unittest.TestCase):
    def test_relation_material_extension_ignores_only_verified_global_fingerprint(self):
        rows = [material()]
        changed = deepcopy(rows)
        changed[0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
        self.assertEqual(relation_input(rows)['input_identity'], relation_input(changed)['input_identity'])
        changed[0]['source_refs'][0]['receipt_sha256'] = 'e' * 64
        self.assertNotEqual(relation_input(rows)['input_identity'], relation_input(changed)['input_identity'])

    def test_relation_card_extension_preserves_raw_content_but_ignores_global_fingerprint(self):
        cards = [dict(card_id='3' * 64, source_refs=[binding()], original_source_row={'content':'fixture'})]
        changed = deepcopy(cards)
        changed[0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
        self.assertEqual(relation_input([], cards)['input_identity'], relation_input([], changed)['input_identity'])
        changed[0]['original_source_row']['content'] = 'different'
        self.assertNotEqual(relation_input([], cards)['input_identity'], relation_input([], changed)['input_identity'])


def attention_inputs(card_count: int = 1) -> dict:
    cards = [dict(card_id=digest(['fixture', i]), semantic_status='ACCEPTED',
        symbol='HK.00001', name='研究示例公司', title=f'研究材料 {i}',
        source_refs=[binding()], original_source_row={'content': f'Isolated original row {i}'},
        published_at='2026-10-08T10:00:00+08:00', retrieved_at='2026-10-08T11:00:00+08:00',
        available_at='2026-10-08T11:00:00+08:00', propositions=[],
        relationship_type='NATIVE_HK_ISSUER_EXPLICIT_MENTION',
        identity_source=dict(status='OWNER_VERIFIED', artifact_sha256='9' * 64),
        claim_type='RESEARCH_OPINION', **FLAGS) for i in range(card_count)]
    return dict(context=dict(plan_trade_date=DATE, research_cutoff='2026-10-10T08:00:00+08:00',
                             focus_window_start='2026-10-07T08:00:00+08:00'),
                market_screen=dict(status='NOT_RUN', cards=[], input_identity='6' * 64),
                stocks=[], material_cards=cards, themes=[],
                announcement_observation=dict(status='NOT_RUN'),
                us_market=dict(status='NOT_RUN', raw_industry_up=[], raw_individual_up=[]))


def attention_stage(inputs: dict) -> dict:
    from v4.manager_research import workspace as w
    from v4.manager_research.research_attention import build_research_attention
    # The immutable baseline calls the original pure projector directly at
    # this stage. The repaired stage wraps that same call for identity only.
    # This adapter allows RED replay against before/ without replacing any
    # owner reader, source guard, or projection implementation.
    stage = getattr(w, '_build_research_attention', build_research_attention)
    return stage(DATE, **inputs)


class AttentionIdentityTests(unittest.TestCase):
    def test_attention_stage_global_only_change_keeps_semantic_identity(self):
        inputs = attention_inputs()
        changed = deepcopy(inputs)
        changed['material_cards'][0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
        before, after = attention_stage(inputs), attention_stage(changed)
        self.assertGreater(before['coverage']['company_material_symbol_count'], 0)
        self.assertEqual(before['input_identity'], after['input_identity'])

    def test_attention_business_output_and_original_provenance_are_unchanged(self):
        from v4.manager_research.research_attention import build_research_attention
        inputs = attention_inputs()
        original_inputs = deepcopy(inputs)
        raw = build_research_attention(DATE, **inputs)
        repaired = attention_stage(inputs)
        raw.pop('input_identity')
        repaired.pop('input_identity')
        self.assertEqual(raw, repaired)
        self.assertEqual(inputs, original_inputs)
        self.assertIn(OLD_MANIFEST, json.dumps(repaired))

    def test_attention_receipt_and_available_at_remain_semantic(self):
        original = attention_inputs()
        identity = attention_stage(original)['input_identity']
        changed = deepcopy(original)
        changed['material_cards'][0]['source_refs'][0]['receipt_sha256'] = 'e' * 64
        self.assertNotEqual(identity, attention_stage(changed)['input_identity'])
        changed = deepcopy(original)
        changed['material_cards'][0]['available_at'] = '2026-10-08T12:00:00+08:00'
        self.assertNotEqual(identity, attention_stage(changed)['input_identity'])

    def test_attention_stock_evidence_global_only_change_keeps_semantic_identity(self):
        inputs = attention_inputs()
        inputs['stocks'] = [dict(symbol='HK.00001', evidence=inputs['material_cards'])]
        inputs['material_cards'] = []
        changed = deepcopy(inputs)
        changed['stocks'][0]['evidence'][0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
        self.assertEqual(attention_stage(inputs)['input_identity'], attention_stage(changed)['input_identity'])

    def test_semantic_reprojection_error_is_not_silently_ignored(self):
        from v4.manager_research.research_attention import build_research_attention
        def fail_semantic(date, **inputs):
            ref = inputs['material_cards'][0]['source_refs'][0]
            if 'manifest_sha256' not in ref:
                raise ValueError('ISOLATED_SEMANTIC_REPROJECTION_FAILURE')
            return build_research_attention(date, **inputs)
        with patch('v4.manager_research.research_attention.build_research_attention', side_effect=fail_semantic):
            with self.assertRaisesRegex(ValueError, 'ISOLATED_SEMANTIC_REPROJECTION_FAILURE'):
                attention_stage(attention_inputs())


class OuterIdentityTests(unittest.TestCase):
    def extend(self, value=None, **changes):
        from v4.manager_research import workspace as w
        fn = getattr(w, '_extend_workspace_identity', None)
        self.assertTrue(callable(fn), 'outer identity stage must record all extension components')
        inputs = dict(research_attention=dict(input_identity='1' * 64),
            announcement_inputs=dict(input_identity='2' * 64, reviewed_analysis=dict(input_identity='3' * 64)),
            announcement_review=dict(product_identity=dict(sha256='4' * 64)),
            us_market=dict(source_identity=dict(payload_sha256='5' * 64)),
            mapping_identities=['6' * 64])
        inputs.update(changes)
        value = deepcopy(value) if value is not None else current_plan()
        fn(value, **inputs)
        return value

    def test_every_outer_extension_remains_identity_sensitive_and_diagnosable(self):
        original = self.extend()
        changes = [dict(research_attention=dict(input_identity='e' * 64)),
            dict(announcement_inputs=dict(input_identity='e' * 64, reviewed_analysis=dict(input_identity='3' * 64))),
            dict(announcement_inputs=dict(input_identity='2' * 64, reviewed_analysis=dict(input_identity='e' * 64))),
            dict(announcement_review=dict(product_identity=dict(sha256='e' * 64))),
            dict(us_market=dict(source_identity=dict(payload_sha256='e' * 64))),
            dict(mapping_identities=['e' * 64])]
        for change in changes:
            with self.subTest(component=next(iter(change))):
                value = self.extend(**change)
                self.assertNotEqual(original['input_identity'], value['input_identity'])
                before, after = original['input_identity_components']['digests'], value['input_identity_components']['digests']
                self.assertTrue(any(key.startswith('outer.') and before[key] != after[key] for key in before))
                self.assertLessEqual(len(after), 32)

    def test_optional_extension_admission_is_not_dropped(self):
        original = self.extend()
        for change in (dict(announcement_inputs=dict(input_identity='2' * 64)),
                       dict(announcement_review={}), dict(us_market={}), dict(mapping_identities=[])):
            with self.subTest(component=next(iter(change))):
                self.assertNotEqual(original['input_identity'], self.extend(**change)['input_identity'])

    def test_global_only_change_with_all_outer_extensions_remains_current(self):
        before = self.extend()
        rows = [material()]
        rows[0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
        after = self.extend(current_plan(rows))
        with tempfile.TemporaryDirectory(prefix='manager-outer-identity-') as directory:
            store = LocalPlanStore(Path(directory))
            product, _ = write_owner_fixture(store, before)
            from v4.manager_research.workspace import _readback_plan
            result = _readback_plan(store, DATE, after)
            self.assertEqual(result['plan_product']['status'], 'CURRENT')
            self.assertEqual(result['plan_product']['sha256'], product['sha256'])


class LocalPlanStore:
    """Filesystem transport fixture; production seals and guards stay active."""
    def __init__(self, root: Path):
        self.root = root

    def _read(self, path: Path):
        return json.loads(path.read_text()) if path.is_file() else None

    def _write_atomic(self, path: Path, value: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False))


def current_plan(rows: list[dict] | None = None) -> dict:
    value = build_workspace(DATE, catalyst={}, stage=None, close=None, materials=rows or [material()],
        plan_context=dict(plan_trade_date=DATE, market_session='20261008',
                          focus_window_start='2026-10-07T08:00:00+08:00',
                          research_cutoff='2026-10-10T08:00:00+08:00'))
    value['date_bindings'] = dict(plan_date=DATE, selection_date=DATE, announcement_date='20261008')
    value['existing_material_coverage'] = {}
    return value


def write_owner_fixture(store: LocalPlanStore, workspace: dict) -> tuple[dict, dict]:
    from v4.manager_research import workspace as w
    product = dict(schema_version=w.PLAN_SCHEMA, target_trade_date=DATE, run_id='8' * 32,
                   generated_at='2026-10-10T00:00:00.500000+00:00',
                   owner='ManagerResearchJobService.refresh_workspace_plan',
                   execution_kind='MANUAL_REFRESH', input_identity=workspace['input_identity'],
                   workspace=deepcopy(workspace), **FLAGS)
    product['sha256'] = digest(product)
    attempt = w.seal_attempt(dict(schema_version=w.ATTEMPT_SCHEMA, target_trade_date=DATE,
                run_id=product['run_id'], owner=product['owner'], execution_kind='MANUAL_REFRESH',
                state='PARTIAL', failure_reasons=['ISOLATED_TEST_SOURCE_GAPS'],
                started_at='2026-10-10T00:00:00+00:00', finished_at='2026-10-10T00:00:01+00:00',
                input_identity=workspace['input_identity'], **FLAGS))
    for name in ('latest', product['run_id']):
        store._write_atomic(store.root / 'workspace_plans' / DATE / (name + '.json'), product)
        store._write_atomic(store.root / 'workspace_plan_runs' / DATE / (name + '.json'), attempt)
    return product, attempt


class PlanReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='manager-identity-test-')
        self.addCleanup(self.temp.cleanup)
        self.store = LocalPlanStore(Path(self.temp.name))
        self.read_at = datetime.fromisoformat('2026-10-10T00:00:02+00:00')

    def read(self, current: dict) -> dict:
        from v4.manager_research.workspace import _readback_plan
        return _readback_plan(self.store, DATE, current, read_at=self.read_at)

    def test_global_only_repeat_readback_keeps_same_run_product_and_saved_bytes(self):
        product, _ = write_owner_fixture(self.store, current_plan())
        saved_bytes = {str(path): path.read_bytes() for path in self.store.root.rglob('*.json')}
        rows = [material()]
        rows[0]['source_refs'][0]['manifest_sha256'] = NEW_MANIFEST
        for _ in range(2):
            result = self.read(current_plan(rows))
            self.assertEqual(result['plan_product']['status'], 'CURRENT')
            self.assertIs(result['plan_product']['consumed'], True)
            self.assertEqual(result['plan_product']['run_id'], product['run_id'])
            self.assertEqual(result['plan_product']['sha256'], product['sha256'])
            diagnostic = result['plan_product'].get('input_identity_diagnostics')
            self.assertIsInstance(diagnostic, dict)
            self.assertEqual(diagnostic['status'], 'UNCHANGED')
        self.assertEqual(saved_bytes, {str(path): path.read_bytes() for path in self.store.root.rglob('*.json')})

    def test_material_change_remains_stale_and_identifies_changed_component(self):
        write_owner_fixture(self.store, current_plan())
        rows = [material()]
        rows[0]['source_refs'][0]['receipt_sha256'] = 'e' * 64
        result = self.read(current_plan(rows))
        self.assertEqual(result['plan_product']['status'], 'STALE_INPUTS_CHANGED')
        self.assertIs(result['plan_product']['consumed'], False)
        diagnostic = result['plan_product'].get('input_identity_diagnostics')
        self.assertIsInstance(diagnostic, dict)
        self.assertEqual(diagnostic['status'], 'CHANGED')
        self.assertIn('projection.materials', [row['component'] for row in diagnostic['changed_components']])

    def test_historical_missing_component_evidence_is_cannot_confirm_without_rewrite(self):
        historical = current_plan()
        historical.pop('input_identity_version', None)
        historical.pop('input_identity_components', None)
        historical['input_identity'] = 'f' * 64
        write_owner_fixture(self.store, historical)
        path = self.store.root / 'workspace_plans' / DATE / 'latest.json'
        original_bytes = path.read_bytes()
        result = self.read(current_plan())
        self.assertEqual(result['plan_product']['status'], 'STALE_INPUTS_CHANGED')
        diagnostic = result['plan_product'].get('input_identity_diagnostics')
        self.assertIsInstance(diagnostic, dict)
        self.assertEqual(diagnostic['status'], 'CANNOT_CONFIRM')
        self.assertEqual(diagnostic['changed_components'], [])
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_missing_owner_attempt_remains_unconsumed(self):
        product, _ = write_owner_fixture(self.store, current_plan())
        (self.store.root / 'workspace_plan_runs' / DATE / (product['run_id'] + '.json')).unlink()
        result = self.read(current_plan())
        self.assertEqual(result['plan_product']['status'], 'OWNER_ATTEMPT_UNVERIFIED')
        self.assertIs(result['plan_product']['consumed'], False)
        self.assertEqual(result['plan_product']['reason'], 'WORKSPACE_PLAN_ATTEMPT_MISSING')

    def test_identity_version_mismatch_does_not_reinterpret_historical_plan(self):
        old = current_plan()
        old['input_identity_version'] = 'LEGACY_TEST_CONTRACT'
        write_owner_fixture(self.store, old)
        result = self.read(current_plan())
        self.assertEqual(result['plan_product']['status'], 'STALE_INPUTS_CHANGED')
        self.assertIs(result['plan_product']['consumed'], False)

    def test_changed_component_diagnostics_are_bounded_and_exclude_raw_rows(self):
        old = current_plan()
        self.assertIsInstance(old.get('input_identity_components'), dict)
        old['input_identity_components']['digests'] = {f'component_{i:02}': '1' * 64 for i in range(32)}
        write_owner_fixture(self.store, old)
        new = current_plan()
        new['input_identity'] = '2' * 64
        new['input_identity_components']['digests'] = {f'component_{i:02}': '3' * 64 for i in range(32)}
        result = self.read(new)
        diagnostic = result['plan_product'].get('input_identity_diagnostics')
        self.assertIsInstance(diagnostic, dict)
        self.assertEqual(diagnostic['changed_component_count'], 32)
        self.assertEqual(len(diagnostic['changed_components']), 16)
        self.assertIs(diagnostic['truncated'], True)
        self.assertNotIn('Original research content', json.dumps(diagnostic))
        self.assertLess(len(json.dumps(diagnostic)), 6000)

    def test_invalid_component_evidence_does_not_invent_attribution(self):
        old = current_plan()
        self.assertIsInstance(old.get('input_identity_components'), dict)
        old['input_identity_components']['digests'] = {'raw_content<script>': 'x' * 10000}
        write_owner_fixture(self.store, old)
        new = current_plan()
        new['input_identity'] = '2' * 64
        result = self.read(new)
        diagnostic = result['plan_product'].get('input_identity_diagnostics')
        self.assertIsInstance(diagnostic, dict)
        self.assertEqual(diagnostic['status'], 'CANNOT_CONFIRM')
        self.assertEqual(diagnostic['changed_components'], [])

    def test_tampered_saved_product_remains_readback_failed(self):
        product, _ = write_owner_fixture(self.store, current_plan())
        product['workspace']['materials'][0]['source_row']['content'] = 'tampered'
        self.store._write_atomic(self.store.root / 'workspace_plans' / DATE / 'latest.json', product)
        result = self.read(current_plan())
        self.assertEqual(result['plan_product']['status'], 'READBACK_FAILED')

    def test_date_binding_and_cutoff_guards_remain_fail_closed(self):
        write_owner_fixture(self.store, current_plan())
        changed = current_plan()
        changed['date_bindings']['announcement_date'] = '20261007'
        self.assertIs(self.read(changed)['plan_product']['consumed'], False)
        changed = current_plan()
        changed['plan_context']['research_cutoff'] = '2026-10-10T07:59:00+08:00'
        self.assertEqual(self.read(changed)['plan_product']['status'], 'PLAN_AFTER_READ_CUTOFF')


def archive_payload() -> dict:
    from contracts.research import DEDUPE_KEY_FIELDS
    when = '2026-10-07T10:00:00+08:00'
    article = dict(article_id='a' * 64, dedupe_key='b' * 64, archive_date=SOURCE_DATE,
        stock_code='HK.00001', stock_name='研究示例公司', source_type='zsxq', source_name='isolated_fixture',
        source_title='Isolated research material', source_path_sha256='c' * 64,
        url='https://example.invalid/isolated-research-fixture', theme='AI_APPLICATION', catalyst='fixture',
        evidence_sentence='Isolated research observation.', evidence_level='RESEARCH_OPINION', confidence=0.5,
        published_at=when, collected_at=when, first_seen_at=when, duplicate_evidence_count=1,
        source_dedup_keys=['fixture'], recommendation_status='RESEARCH_ONLY')
    pool = dict(stock_code='HK.00001', stock_name='研究示例公司', archive_date=SOURCE_DATE,
        research_score=1, research_status='RESEARCH_ONLY', evidence_count=1, source_count=1,
        strong_evidence_count=0, medium_evidence_count=0, weak_evidence_count=1,
        source_types=['zsxq'], themes=['AI_APPLICATION'], top_catalysts=['fixture'],
        first_seen_at=when, collected_at=when, formal_overlap=False, stage_overlap=False,
        recommendation_status='RESEARCH_ONLY')
    return dict(schema_version='v3_5.research_archive.v1', archive_date=SOURCE_DATE, status='READY',
        timezone='Asia/Shanghai', source_input_sha256='d' * 64, source_schema_version='isolated_test_fixture.v1',
        source_generated_at=when, dedupe_key_fields=list(DEDUPE_KEY_FIELDS),
        article_count=1, stock_pool_count=1, source_counts={'zsxq': 1}, articles=[article], stock_pool=[pool],
        cannot_confirm=['ISOLATED_TEST_FIXTURE_NOT_LIVE_EVIDENCE'], write_policy='read_only',
        recommendation_status='RESEARCH_ONLY', production_allowed=False, buy_gate_updated=False, orders_sent=False)


class ExactSourceGuardTests(unittest.TestCase):
    def setUp(self):
        from infrastructure.research_lane_source import ResearchLaneSource
        self.temp = tempfile.TemporaryDirectory(prefix='manager-original-source-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = ResearchLaneSource(self.root)
        self.payload = archive_payload()
        self.write_bound_fixture(self.payload)

    def write_json(self, relative: str, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')))

    def write_bound_fixture(self, payload):
        from infrastructure.data_store import _sha256
        self.write_json(f'research/archives/{SOURCE_DATE}.json', payload)
        self.write_json(f'receipts/research/archives/{SOURCE_DATE}.json', self.source.store._receipt(payload, _sha256(payload)))
        self.write_json('manifest.json', {f'research/archives/{SOURCE_DATE}.json': _sha256(payload)})

    def read_materials(self):
        from v4.manager_research.existing_materials import _read_archive
        return _read_archive(self.source, SOURCE_DATE, '')

    def test_real_owner_read_of_unchanged_binding_ignores_unconsumed_registry_entry(self):
        before, _, old_binding = self.read_materials()
        manifest = json.loads((self.root / 'manifest.json').read_text())
        manifest['unconsumed/isolated-fixture.json'] = 'e' * 64
        self.write_json('manifest.json', manifest)
        after, _, new_binding = self.read_materials()
        self.assertEqual(old_binding['status'], 'VERIFIED')
        self.assertNotEqual(old_binding['manifest_sha256'], new_binding['manifest_sha256'])
        self.assertEqual(old_binding['payload_sha256'], new_binding['payload_sha256'])
        self.assertEqual(old_binding['receipt_sha256'], new_binding['receipt_sha256'])
        self.assertEqual(projection(before)['input_identity'], projection(after)['input_identity'])
        self.assertEqual(after[0]['source_refs'][0], new_binding)

    def test_consumed_payload_bytes_without_rebinding_are_rejected_by_original_guard(self):
        changed = deepcopy(self.payload)
        changed['articles'][0]['evidence_sentence'] += ' changed'
        self.write_json(f'research/archives/{SOURCE_DATE}.json', changed)
        with self.assertRaisesRegex(ValueError, 'manifest or receipt mismatch'):
            self.read_materials()

    def test_consumed_receipt_bytes_are_rejected_by_original_guard(self):
        path = self.root / f'receipts/research/archives/{SOURCE_DATE}.json'
        receipt = json.loads(path.read_text())
        receipt['payload_sha256'] = 'e' * 64
        self.write_json(str(path.relative_to(self.root)), receipt)
        with self.assertRaisesRegex(ValueError, 'manifest or receipt mismatch'):
            self.read_materials()

    def test_consumed_manifest_entry_change_is_rejected_by_original_guard(self):
        self.write_json('manifest.json', {f'research/archives/{SOURCE_DATE}.json': 'e' * 64})
        with self.assertRaisesRegex(ValueError, 'manifest or receipt mismatch'):
            self.read_materials()

    def test_missing_receipt_is_rejected_by_original_guard(self):
        (self.root / f'receipts/research/archives/{SOURCE_DATE}.json').unlink()
        with self.assertRaisesRegex(ValueError, 'manifest or receipt mismatch'):
            self.read_materials()

    def test_exact_date_mismatch_is_rejected_even_when_rebound_hashes_match(self):
        changed = deepcopy(self.payload)
        changed['archive_date'] = '20261008'
        changed['articles'][0]['archive_date'] = '20261008'
        changed['stock_pool'][0]['archive_date'] = '20261008'
        self.write_bound_fixture(changed)
        with self.assertRaisesRegex(ValueError, 'manifest or receipt mismatch'):
            self.read_materials()

    def test_valid_changed_consumed_payload_still_changes_semantic_identity(self):
        before, _, _ = self.read_materials()
        changed = deepcopy(self.payload)
        changed['articles'][0]['evidence_sentence'] += ' changed'
        self.write_bound_fixture(changed)
        after, _, _ = self.read_materials()
        self.assertNotEqual(projection(before)['input_identity'], projection(after)['input_identity'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
