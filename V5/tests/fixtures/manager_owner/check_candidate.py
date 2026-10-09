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
