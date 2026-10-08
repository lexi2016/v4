import copy
import unittest
from v5_shadow.digests import sha256_json

class ManagerAttentionTests(unittest.TestCase):
    def binding(self,payload):
        return dict(payload=payload,payload_sha256=sha256_json(payload),available_at='2026-09-24T08:03:00+08:00',
                    product_state='AVAILABLE',source_id='SYNTHETIC_EXAMPLE')
    def request(self):
        announcement=dict(status='SUCCEEDED',official_documents=[dict(event_id='9'*64,symbol='HK.05432',
            title='SIMULATED non-screen issuer event',published_at='2026-09-24T08:00:00+08:00',
            retrieved_at='2026-09-24T08:02:00+08:00',available_at='2026-09-24T08:02:00+08:00',body_status='BODY_PARSED')])
        return dict(plan_date='20260924',selection_date='20260923',announcement_publication_date='20260924',
            data_kind='SYNTHETIC',context=dict(plan_trade_date='20260924',research_cutoff='2026-09-24T09:27:35.408396+08:00'),
            lanes=dict(screen=None,announcement=self.binding(announcement),us=None,materials=None))
    def run_request(self,r):
        from v5_shadow.manager_attention import run_manager_attention
        return run_manager_attention(r)
    def test_official_lane_survives_missing_screen_and_us(self):
        r=self.request();before=copy.deepcopy(r);out=self.run_request(r);cards=out['artifact']['cards']
        self.assertEqual(r,before);self.assertEqual(len(cards),1);self.assertEqual(cards[0]['symbol'],'HK.05432')
        self.assertEqual(cards[0]['research_attention_score'],42)
        self.assertEqual(out['artifact']['status'],'CANNOT_CONFIRM');self.assertFalse(out['input_provenance_verified'])
    def test_three_dates_remain_distinct(self):
        out=self.run_request(self.request());self.assertEqual(out['selection_date'],'20260923')
        self.assertEqual(out['plan_date'],'20260924');self.assertEqual(out['artifact']['target_trade_date'],'20260924')
    def test_bad_us_digest_does_not_erase_announcement(self):
        r=self.request();r['lanes']['us']=self.binding(dict(status='READY'));r['lanes']['us']['payload_sha256']='a'*64
        out=self.run_request(r);self.assertEqual(len(out['artifact']['cards']),1)
        self.assertFalse(out['lanes']['us']['accepted']);self.assertIn('DIGEST',out['lanes']['us']['reason'])
    def test_latest_failed_attempt_does_not_erase_retained_product(self):
        r=self.request();p=r['lanes']['announcement']['payload'];p.update(status='FAILED',previous_product_retained=True)
        r['lanes']['announcement']['payload_sha256']=sha256_json(p)
        self.assertEqual(len(self.run_request(r)['artifact']['cards']),1)
    def test_late_lane_excluded_not_retimed(self):
        r=self.request();r['lanes']['announcement']['available_at']='2026-09-24T10:00:00+08:00'
        out=self.run_request(r);self.assertFalse(out['lanes']['announcement']['accepted']);self.assertEqual(out['artifact']['cards'],[])
    def test_context_plan_mismatch_rejected(self):
        r=self.request();r['context']['plan_trade_date']='20260925'
        with self.assertRaisesRegex(ValueError,'MANAGER_PLAN_DATE_MISMATCH'):self.run_request(r)
    def test_invalid_cutoff_rejected(self):
        r=self.request();r['context']['research_cutoff']='2026-09-24T08:00:00'
        with self.assertRaises(ValueError):self.run_request(r)
    def test_missing_inputs_not_zero_mapping_result(self):
        r=self.request();r['lanes']={k:None for k in r['lanes']};out=self.run_request(r)
        self.assertEqual(out['artifact']['cards'],[])
        self.assertIsNone(out['artifact']['us_mapping_diagnostics']['accepted_hk_mapping_count'])
    def test_product_marked_invalid_cannot_contribute(self):
        r=self.request();r['lanes']['announcement']['product_state']='INVALID'
        out=self.run_request(r);self.assertEqual(out['artifact']['cards'],[])

    def test_bad_us_shape_preserves_official_lane(self):
        r=self.request();r['lanes']['us']=self.binding(dict(status='READY',raw_industry_up=1))
        out=self.run_request(r);self.assertEqual(len(out['artifact']['cards']),1)
        self.assertFalse(out['lanes']['us']['accepted'])
    def test_bad_material_nested_shape_preserves_official_lane(self):
        r=self.request();r['lanes']['materials']=self.binding(dict(stocks=[dict(evidence=1)],material_cards=[],themes=[]))
        out=self.run_request(r);self.assertEqual(len(out['artifact']['cards']),1);self.assertFalse(out['lanes']['materials']['accepted'])
    def test_us_complete_cannot_replace_missing_materials(self):
        r=self.request();r['lanes']['us']=self.binding(dict(status='READY',mapping_eligible=True,captured_at='2026-09-24T08:00:00+08:00',
            raw_industry_up=[],raw_individual_up=[],research_material_input=dict(complete=True,gaps=None)))
        out=self.run_request(r);self.assertIsNone(out['artifact']['us_mapping_diagnostics']['accepted_hk_mapping_count'])
        self.assertEqual(out['artifact']['us_mapping_diagnostics']['assessment_state'],'NOT_EVALUATED')
        self.assertEqual(len(out['artifact']['cards']),1)
    def test_future_screen_isolated_from_announcement(self):
        r=self.request();r['lanes']['screen']=self.binding(dict(schema_version='v4.manager_research.rebound_v3_screen.v1',
            target_trade_date='20260924',verified_session=20260925,status='READY',main_screen_ready=True))
        out=self.run_request(r);self.assertEqual(len(out['artifact']['cards']),1)
        self.assertEqual(out['lanes']['screen']['reason'],'SCREEN_FUTURE_SESSION')

if __name__=='__main__':unittest.main()
