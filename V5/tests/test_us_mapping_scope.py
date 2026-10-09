import copy
import unittest
from v5_shadow.us_mapping_scope import describe_scope

class UsMappingScopeTests(unittest.TestCase):
    def setUp(self):
        identity=dict(status='VERIFIED',payload_sha256='a'*64,manifest_sha256='b'*64,receipt_sha256='c'*64)
        self.reviewed={'artifact_sha256':'d'*64,'cards':[{'daily_match_symbols':['AAA'],'hk_symbol':'HK.00001'}]}
        self.daily=dict(research_cutoff='2026-10-09T10:00:00Z',generated_at='2026-10-09T11:00:00Z',source_status='READY',source_identity=identity,us_session_date='20261008',relation_artifact_sha256='d'*64,
            matches=[],coverage={'configured_us_universe_count':33})
        self.market=dict(research_cutoff='2026-10-09T12:00:00Z',status='READY',source_identity=copy.deepcopy(identity),expected_us_session='20261008',raw_individual_up=[{'symbol':'BBB','change_pct':2}])

    def test_outside_registry_is_unassessed_not_zero_result(self):
        value=describe_scope(self.daily,self.market,self.reviewed)
        self.assertEqual(value['assessed_rising_symbol_count'],0);self.assertEqual(value['unassessed_rising_symbol_count'],1)
        self.assertIsNone(value['rows'][0]['matched_relation_count']);self.assertIsNone(value['broader_relation_result'])
        self.assertFalse(value['full_market_coverage'])

    def test_existing_reviewed_match_preserved_without_eligibility_promotion(self):
        self.market['raw_individual_up']=[{'symbol':'AAA','change_pct':2}];self.daily['matches']=[{'us_symbol':'AAA','hk_symbol':'HK.00001'}]
        before=copy.deepcopy(self.daily);value=describe_scope(self.daily,self.market,self.reviewed)
        self.assertEqual(value['rows'][0]['matched_relation_count'],1);self.assertEqual(self.daily,before)
        self.assertFalse(value['formal_eligible'])

    def test_old_session_does_not_describe_current_market(self):
        self.daily['us_session_date']='20261007'
        value=describe_scope(self.daily,self.market,self.reviewed)
        self.assertIsNone(value['rows']);self.assertIsNone(value['unassessed_rising_symbol_count'])

    def test_wrong_raw_sha_rejects_scope_counts(self):
        self.market['source_identity']['payload_sha256']='f'*64
        self.assertIsNone(describe_scope(self.daily,self.market,self.reviewed)['rising_individual_count'])

    def test_relation_not_available_at_cutoff_is_not_assessed(self):
        self.daily['relation_artifact_sha256']=None
        self.assertIsNone(describe_scope(self.daily,self.market,self.reviewed)['assessed_rising_symbol_count'])

    def test_missing_source_is_unknown_and_legacy_fields_not_mutated(self):
        self.market.update(status='INPUT_MISSING',source_identity=None)
        before=copy.deepcopy(self.daily)
        value=describe_scope(self.daily,self.market,self.reviewed)
        self.assertEqual(value['status'],'CANNOT_CONFIRM');self.assertIsNone(value['configured_sample_count'])
        self.assertEqual(self.daily,before)

    def test_late_recovery_is_not_backfilled_before_its_generation(self):
        self.daily['generated_at']='2026-10-09T13:00:00Z'
        self.assertIsNone(describe_scope(self.daily,self.market,self.reviewed)['rising_individual_count'])
