"""Disposable-process checks of the production-loaded original owner."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from v5_shadow.manager_plan import load_owner


class ProductionAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = load_owner()

    def setUp(self):
        self.cp = '2026-10-08T19:59:59.999999Z'
        self.cd = '2026-10-08T09:00:00.123456+08:00'
        self.source = dict(owner='ResearchPeripheralStore', source='external_finance',
            session_date='20261007', payload_path='research/peripherals/20261007/external_finance.json',
            receipt_path='receipts/research/peripherals/20261007/external_finance.json',
            manifest_path='research/peripherals/manifest.json', status='VERIFIED',
            payload_sha256='a'*64, receipt_sha256='b'*64, manifest_sha256='c'*64)
        self.daily = dict(target_trade_date='20261008', us_session_date='20261007',
            status='VALID_EMPTY', source_status='READY', source_identity=deepcopy(self.source),
            research_cutoff=self.cd, generated_at='2026-10-08T09:00:00+08:00',
            artifact_sha256='d'*64, matches=[])
        self.context = dict(plan_trade_date='20261008', research_cutoff=self.cp, us_market_session=None)
        self.bridge = dict(target_trade_date='20261008', expected_us_session='20261007',
            research_cutoff=self.cp, status='READY', source_identity=deepcopy(self.source))

    def reason(self):
        from v5_shadow.manager_plan_gate import rejection_reason
        return rejection_reason(self.daily, '20261008', self.context, self.bridge)

    def test_overlay_enumerates_original_files_with_suffix_and_owner_routing(self):
        import importlib
        import tempfile
        from v5_shadow.manager_plan import OverlayIO
        SafeRoot = importlib.import_module('infrastructure.owned_io').SafeRoot
        with tempfile.TemporaryDirectory(prefix='v5-overlay-files-') as temporary:
            root = Path(temporary)
            private, durable = root/'private', root/'durable'
            private.mkdir(); durable.mkdir()
            private_io, durable_io = SafeRoot(private), SafeRoot(durable)
            announcement = 'workspace_announcements/20261008/_auto_commits'
            plans = 'workspace_plans/20261008'
            # Real entries in both roots prove routing and filtering; empty
            # directories or a stubbed files() cannot satisfy these assertions.
            for io, relative, names in (
                (private_io, announcement, ['b.json', 'a.json', 'body.txt']),
                (durable_io, announcement, ['wrong-owner.json']),
                (durable_io, plans, ['saved.json', 'note.txt']),
                (private_io, plans, ['wrong-plan.json']),
                (private_io, 'workspace_plans_extra', ['private.json'])):
                for name in names:
                    io.write_bytes(relative+'/'+name, b'{}')
            overlay = OverlayIO(durable_io, private_io)
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(overlay.files(announcement), ['a.json', 'b.json'])
            self.assertEqual(overlay.files(announcement, suffix='.txt'), ['body.txt'])
            self.assertEqual(overlay.files(plans), ['saved.json'])
            self.assertEqual(overlay.files(plans, suffix='.txt'), ['note.txt'])
            self.assertEqual(overlay.files('workspace_plans_extra'), ['private.json'])
            self.assertEqual(overlay.files('absent'), [])
            self.assertEqual(overlay.files(), [])
            self.assertEqual(overlay.read_bytes(plans+'/saved.json'), b'{}')
            with overlay.directory(plans) as fd:
                self.assertIsInstance(fd, int)
            after = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(after, before)

    def screen_projection(self, context, screen):
        return self.owner.build_workspace('20261008',
            catalyst=dict(status='CANNOT_CONFIRM', cards=[], gaps=['FIXTURE_OWNER_NOT_BOUND']),
            plan_context=context, market_screen=screen)

    def test_screen_cutoff_only_change_preserves_identity_and_payload_timestamps(self):
        context = self.owner.plan_context('20261008', now=datetime.fromisoformat('2026-10-09T10:00:00+08:00'))
        screen = self.owner.read_rebound_screen(None, context)
        later_context = deepcopy(context)
        later_context['research_cutoff'] = '2026-10-09T10:05:00+08:00'
        later_screen = deepcopy(screen)
        later_screen['data_context']['research_cutoff'] = later_context['research_cutoff']
        before = deepcopy((context, screen, later_context, later_screen))
        first = self.screen_projection(context, screen)
        second = self.screen_projection(later_context, later_screen)
        self.assertEqual(first['market_screen'], screen)
        self.assertEqual(second['market_screen'], later_screen)
        self.assertEqual((context, screen, later_context, later_screen), before)
        self.assertEqual(first['input_identity'], second['input_identity'])

    def test_screen_source_session_phase_and_admission_still_invalidate_identity(self):
        context = self.owner.plan_context('20261008', now=datetime.fromisoformat('2026-10-09T10:00:00+08:00'))
        screen = self.owner.read_rebound_screen(None, context)
        baseline = self.screen_projection(context, screen)['input_identity']
        variants = []
        source = deepcopy(screen);source['authority'] = {'source_sha256':'a'*64};variants.append(('source SHA', source))
        session = deepcopy(screen);session['data_context']['market_session'] = '20261007';variants.append(('daily session', session))
        phase = deepcopy(screen);phase['data_context']['screen_phase'] = 'PREOPEN_PLAN';variants.append(('phase', phase))
        admission = deepcopy(screen);admission['gaps'].append('OWNER_ADMISSION_CHANGED');variants.append(('admission', admission))
        for label, changed in variants:
            with self.subTest(change=label):
                self.assertNotEqual(changed, screen)
                self.assertNotEqual(self.screen_projection(context, changed)['input_identity'], baseline)

    def test_same_session_earlier_cutoff_and_truncated_generation_are_accepted(self):
        self.assertIsNone(self.reason())
        self.daily['status']='COMPLETED'
        self.assertIsNone(self.reason())
        self.daily['generated_at']=self.cp
        self.assertIsNone(self.reason())
        self.context['research_cutoff']='2026-10-09T03:59:59.999999+08:00'
        self.assertIsNone(self.reason())

    def test_close_boundary_advances_expected_session(self):
        self.context['research_cutoff']='2026-10-08T20:00:00Z'
        self.bridge['expected_us_session']='20261008'
        self.bridge['research_cutoff']=self.context['research_cutoff']
        self.assertIsNotNone(self.reason())

    def test_every_source_identity_component_is_bound(self):
        for key in self.source:
            with self.subTest(key=key):
                saved=deepcopy(self.bridge)
                self.bridge['source_identity'][key]='different'
                self.assertIsNotNone(self.reason())
                self.bridge=saved

    def test_missing_current_source_cannot_consume_saved_success(self):
        self.bridge['status']='INPUT_MISSING'
        self.assertIsNotNone(self.reason())

    def test_dates_and_time_boundaries_fail_closed(self):
        for key,value in [('target_trade_date','20261009'),('research_cutoff','2026-10-08T20:00:00Z'),
                          ('research_cutoff','2026-10-08T12:00:00'),('research_cutoff','invalid'),
                          ('generated_at','2026-10-08T20:00:00Z')]:
            with self.subTest(key=key,value=value):
                before=deepcopy(self.daily);self.daily[key]=value
                self.assertIsNotNone(self.reason());self.daily=before
        self.context['research_cutoff']='2031-10-08T20:00:00Z'
        self.assertIsNotNone(self.reason())


if __name__=='__main__':unittest.main()
