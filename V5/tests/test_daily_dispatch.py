from datetime import datetime,timezone
from unittest.mock import patch
from v5_shadow.daily_dispatch import dispatch_due
from v5_shadow.digests import sha256_json
from daily_ledger_fixture import make_ledger_fixture
import unittest

class DailyDispatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture=make_ledger_fixture(self.addCleanup);self.root=self.fixture.root
        self.clock=patch('v5_shadow.daily_dispatch.datetime');self.mock=self.clock.start();self.addCleanup(self.clock.stop)
        self.mock.now.return_value=datetime.fromisoformat('2026-10-09T01:00:00+00:00')

    def job(self,lane):
        request={'fixture':'SYNTHETIC_NOT_CAPTURE','target_date':'20261009','now':self.fixture.identity['research_cutoff']}
        return dict(lane=lane,identity=dict(self.fixture.identity,lane=lane,input_sha256=sha256_json(request)),owner_request=request,
            scheduled_at='2026-10-09T00:00:00Z',deadline='2026-10-09T02:00:00Z',half_day_bound=False,max_attempts=2)

    def binding(self, invoke):
        return dict(invoke=invoke,**{key:self.fixture.identity[key] for key in ('code_sha256','config_sha256','dependency_sha256')})

    def test_one_owner_failure_does_not_stop_other_lanes_or_retry_unknown(self):
        calls=[]
        def bad(*args):calls.append('bad');raise TimeoutError()
        def good(*args):calls.append('good');return self.fixture.success
        jobs=[self.job('announcement'),self.job('us_mapping'),self.job('rebound')]
        bindings={'announcement':self.binding(bad),'us_mapping':self.binding(good),'rebound':self.binding(good)}
        result=dispatch_due(jobs,bindings,self.root)
        self.assertEqual([r['status'] for r in result['lanes']],['OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY','SUCCEEDED','SUCCEEDED'])
        dispatch_due(jobs,bindings,self.root);self.assertEqual(calls,['bad','good','good'])
        self.assertFalse(result['natural_verified'])

    def test_bad_lane_contract_does_not_block_valid_lane(self):
        result=dispatch_due([{'lane':'announcement'},self.job('us_mapping')],{'us_mapping':self.binding(lambda *args:self.fixture.success)},self.root)
        self.assertEqual(result['lanes'][0]['status'],'LANE_ADMISSION_FAILED');self.assertEqual(result['lanes'][1]['status'],'SUCCEEDED')

    def test_missed_slot_and_missing_adapter_never_execute(self):
        missed=self.job('announcement');missed['deadline']='2026-10-09T00:30:00Z'
        result=dispatch_due([missed,self.job('rebound')],{},self.root)
        self.assertEqual([r['status'] for r in result['lanes']],['MISSED_WINDOW_NO_BACKFILL','OWNER_ADAPTER_NOT_BOUND'])

    def test_weekend_calendar_and_historical_target_rejected(self):
        self.mock.now.return_value=datetime.fromisoformat('2026-10-10T01:00:00+00:00')
        job=self.job('us_mapping');job['identity']['target_date']='20261010'
        result=dispatch_due([job,self.job('rebound')],{},self.root)
        self.assertEqual([r['status'] for r in result['lanes']],['HK_SECURITIES_CALENDAR_NOT_OPEN','NOT_CURRENT_TARGET_DATE'])

    def test_changed_binding_or_owner_cutoff_does_not_start(self):
        binding=self.binding(lambda *args:self.fail('must not invoke'))
        job=self.job('us_mapping');job['identity']['code_sha256']='f'*64
        self.assertEqual(dispatch_due([job],{'us_mapping':binding},self.root)['lanes'][0]['status'],'OWNER_BINDING_IDENTITY_MISMATCH')
        job=self.job('us_mapping');job['owner_request']['now']='2026-10-08T00:00:00Z'
        job['identity']['input_sha256']=sha256_json(job['owner_request'])
        self.assertEqual(dispatch_due([job],{'us_mapping':binding},self.root)['lanes'][0]['status'],'US_OWNER_DATE_CUTOFF_MISMATCH')
