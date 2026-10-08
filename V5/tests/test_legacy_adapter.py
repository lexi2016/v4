import copy, unittest
from datetime import datetime,timezone
from v5_shadow.contracts import RuntimeIdentity,parse_request
from v5_shadow.legacy_adapter import build_shadow_result, run_legacy_screen
from test_contracts import request

class LegacyTests(unittest.TestCase):
    def setUp(self):
        self.request=parse_request(request())
        self.runtime=RuntimeIdentity('rebound_shadow','r1','a'*64,'3.12.14','b'*64,'c'*64,'e'*64,datetime.now(timezone.utc))
        self.start=datetime.now(timezone.utc)
    def legacy(self):
        return dict(schema_version='v4.manager_research.rebound_v3_screen.v1',rule_version='20260923_REBOUND_TWO_GATE_V1',target_trade_date='20261008',status='READY',main_screen_ready=True,input_identity='a'*64,authority={'witness':'synthetic'},coverage=dict(input_candidate_count=1,row_accounted_count=1,history_pending_count=0,screen_unresolved_count=0,strict_count=0,near_count=0,excluded_count=1),strict=[],near=[],excluded=[{'code':'HK.00001'}],pending=[],screen_unresolved=[],gaps=[])
    def build(self,legacy):return build_shadow_result(self.request,self.runtime,legacy,self.start,datetime.now(timezone.utc))
    def test_missing_input_not_zero(self):
        legacy=self.legacy();legacy.update(status='CANNOT_CONFIRM',main_screen_ready=False,input_identity=None)
        result=self.build(legacy)
        self.assertEqual(result.business_status,'CANNOT_CONFIRM');self.assertIsNone(result.evaluated_count)
    def test_complete_valid_empty(self):
        result=self.build(self.legacy())
        self.assertEqual(result.business_status,'VALID_EMPTY');self.assertEqual(result.evaluated_count,1)
        self.assertFalse(result.natural_verified);self.assertEqual(result.formal_eligibility_status,'UNVERIFIED')
    def test_payload_unchanged_and_detached(self):
        legacy=self.legacy();before=copy.deepcopy(legacy);result=self.build(legacy)
        self.assertEqual(result.legacy_screen,before)
        legacy['gaps'].append('changed')
        self.assertEqual(result.legacy_screen,before)
    def test_invalid_accounting_is_unknown(self):
        legacy=self.legacy();legacy['coverage']['row_accounted_count']=0
        self.assertEqual(self.build(legacy).business_status,'CANNOT_CONFIRM')
    def test_unknown_status_is_failed(self):
        legacy=self.legacy();legacy['status']='MAGIC'
        self.assertEqual(self.build(legacy).business_status,'FAILED')
    def test_partial_not_completed(self):
        legacy=self.legacy();legacy['status']='READY_WITH_GAPS';legacy['gaps']=['not_complete']
        self.assertEqual(self.build(legacy).business_status,'PARTIAL')
    def test_wrong_date_rejected(self):
        legacy=self.legacy();legacy['target_trade_date']='20260930'
        with self.assertRaises(ValueError):self.build(legacy)
    def test_execution_clock_cannot_reverse(self):
        with self.assertRaises(ValueError):build_shadow_result(self.request,self.runtime,self.legacy(),datetime.now(timezone.utc),self.start)
    def test_unsafe_flags_do_not_leak(self):
        result=self.build(self.legacy())
        self.assertTrue(result.safety.research_only);self.assertFalse(result.safety.orders_sent)
if __name__=='__main__':unittest.main()
