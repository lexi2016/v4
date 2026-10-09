from datetime import datetime,timezone
from unittest.mock import patch
import unittest
import json
from daily_ledger_fixture import make_ledger_fixture
from v5_shadow.daily_owner_adapters import read_announcement_owner,rebound_receipt,run_manager_daily,blocked
from v5_shadow.daily_tick import launchd_contract,tick,LABEL
from v5_shadow.run_ledger import claim_run,finish_run


class DailyOwnerAdapterTests(unittest.TestCase):
    def test_consumed_announcement_without_decision_stays_blocked(self):
        with patch('v5_shadow.announcement_offline_reader.read_owner',return_value={'consumption':{'status':'CONSUMED'}}) as reader:
            result=read_announcement_owner({'binding':{'target_date':'20261009'},'cutoff':'2026-10-09T01:00:00Z'},'attempt')
        self.assertEqual(reader.call_count,2);self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('ANNOUNCEMENT_DECISION_REVIEWER_ADAPTER_NOT_BOUND',result['reason_codes'])

    def test_announcement_changed_readback_rejected(self):
        with patch('v5_shadow.announcement_offline_reader.read_owner',side_effect=[{'consumption':{}},{'consumption':{'changed':True}}]):
            with self.assertRaisesRegex(ValueError,'READBACK_CHANGED'):
                read_announcement_owner({'binding':{},'cutoff':'2026-10-09T01:00:00Z'},'attempt')

    def test_reused_numeric_rebound_is_not_selection_success(self):
        request={'request':{'target_date':'20261009'},'output_root':'/synthetic'}
        result=dict(reference={'run_id':'synthetic'},computation_status='NATIVE_VALUES_OBSERVED',
                    selection_status='CANNOT_CONFIRM',reused=True,reason_codes=[])
        artifact=dict(request=request['request'],run_id='synthetic',computation_status='NATIVE_VALUES_OBSERVED')
        receipt=rebound_receipt(request,'attempt',result,artifact)
        self.assertEqual(receipt['status'],'BLOCKED');self.assertTrue(receipt['product_reference']['reused'])
        self.assertFalse(receipt['product_reference']['natural_verified'])
        artifact['run_id']='wrong'
        with self.assertRaisesRegex(ValueError,'READBACK'):rebound_receipt(request,'attempt',result,artifact)

    def test_blocked_business_does_not_retry_same_input(self):
        fixture=make_ledger_fixture(self.addCleanup)
        finish_run(fixture.root,claim_run(fixture.root,fixture.identity),blocked(None,['WAITING_REVIEWER']))
        result=claim_run(fixture.root,fixture.identity)
        self.assertEqual(result['status'],'RETRY_BLOCKED');self.assertIsNone(result['state']['latest_success'])

    def test_manager_partial_is_saved_read_back_and_not_refreshed_twice(self):
        fixture=make_ledger_fixture(self.addCleanup)
        request=dict(target_date='20261009',now='2026-10-09T01:00:00Z',action='refresh',manager_output_root='/synthetic')
        registration={k:fixture.identity[k] for k in ('code_sha256','config_sha256','dependency_sha256')}
        result=dict(payload={'plan_product':{'run_id':'same','sha256':'a'*64,'status':'PARTIAL'}},
                    readback={'status':'MATCHED','run_id':'same','plan_sha256':'a'*64,'attempt':{'run_id':'same'}})
        with patch('v5_shadow.daily_owner_adapters.datetime') as clock,patch('v5_shadow.manager_plan.run_manager_plan',return_value=result) as owner:
            clock.now.return_value=datetime(2026,10,9,2,tzinfo=timezone.utc)
            saved=run_manager_daily(request,fixture.root,registration)
            again=run_manager_daily(request,fixture.root,registration)
        self.assertEqual(owner.call_count,2)  # refresh + ordinary workspace read
        self.assertEqual(saved['state']['attempts'][-1]['status'],'BLOCKED')
        self.assertEqual(again['status'],'RETRY_BLOCKED')

    def test_manager_wrong_attempt_never_commits_success(self):
        fixture=make_ledger_fixture(self.addCleanup)
        request=dict(target_date='20261009',now='2026-10-09T01:00:00Z',action='refresh')
        registration={k:fixture.identity[k] for k in ('code_sha256','config_sha256','dependency_sha256')}
        result=dict(payload={'plan_product':{'run_id':'same','sha256':'a'*64}},
                    readback={'status':'MATCHED','run_id':'same','plan_sha256':'a'*64,'attempt':{'run_id':'wrong'}})
        with patch('v5_shadow.daily_owner_adapters.datetime') as clock,patch('v5_shadow.manager_plan.run_manager_plan',return_value=result):
            clock.now.return_value=datetime(2026,10,9,2,tzinfo=timezone.utc)
            with self.assertRaisesRegex(ValueError,'SAME_ATTEMPT'):run_manager_daily(request,fixture.root,registration)

    def test_disabled_tick_does_not_touch_owners_or_roots(self):
        self.assertEqual(tick({'enabled':False})['status'],'DISABLED')

    def test_launchd_contract_is_separate_disabled_and_reuses_tick(self):
        value=launchd_contract('/private/config.json',python='/private/python')
        self.assertEqual(value['Label'],LABEL);self.assertTrue(value['Disabled']);self.assertFalse(value['RunAtLoad'])
        self.assertIn('--config',value['ProgramArguments'])
        with self.assertRaises(ValueError):launchd_contract('relative',python='/private/python')

    def test_tick_bad_announcement_keeps_rebound_observation_and_us_running(self):
        fixture=make_ledger_fixture(self.addCleanup)
        bundle_root=fixture.root/'bundles';bundle_root.mkdir()
        (bundle_root/'.v5-daily-bundles').write_bytes(b'v5.daily-bundles.v1\n')
        common=dict(research_cutoff='2026-10-09T00:00:00Z',scheduled_at='2026-10-09T00:00:00Z',
                    deadline='2026-10-09T02:00:00Z',half_day_bound=False,max_attempts=1)
        requests=dict(announcement={'binding':{'target_date':'20261009'},'cutoff':common['research_cutoff']},
            rebound={'request':{'target_date':'20261009'}},
            us_mapping={'target_date':'20261009','now':common['research_cutoff']})
        (bundle_root/'20261009.json').write_text(json.dumps(dict(target_date='20261009',
            jobs=[dict(common,lane=lane,owner_request=request) for lane,request in requests.items()])))
        binding=dict(invoke=lambda *args:fixture.success,**{k:fixture.identity[k] for k in ('code_sha256','config_sha256','dependency_sha256')})
        with patch('v5_shadow.daily_tick.datetime') as clock,patch('v5_shadow.daily_dispatch.datetime') as dispatch_clock,\
                patch('v5_shadow.daily_tick.read_announcement_owner',side_effect=ValueError('WAIT_REVIEWER')),\
                patch('v5_shadow.daily_tick.run_rebound_owner',return_value=blocked({'reference':{}},['NOT_SELECTION'],readback=True)),\
                patch('v5_shadow.daily_tick.bind_us_owner',return_value=binding):
            clock.now.return_value=dispatch_clock.now.return_value=datetime(2026,10,9,1,tzinfo=timezone.utc)
            result=tick(dict(enabled=True,bundle_root=str(bundle_root),ledger_root=str(fixture.root)))
        self.assertEqual([row['status'] for row in result['lanes']],['OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY','BLOCKED','SUCCEEDED'])
        self.assertEqual(result['manager']['status'],'BLOCKED_POST_OWNER_REQUEST_MISSING')
