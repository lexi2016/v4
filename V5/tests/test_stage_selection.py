"""Recorded-input stage adapter contract, pending Mac execution."""
import copy
import unittest
from v5_shadow.digests import sha256_json

class StageSelectionTests(unittest.TestCase):
    def request(self, market='A_SHARE', count=12):
        rows=[]
        for i in range(count):
            row=dict(code=f'{i+1:06}',trade_date='20261008',stage_id='STAGE_0930_0935',
                     captured_at='2026-10-08T09:35:00+08:00',acquisition_rank=i+1,
                     formal_eligible=False,news_quality_score=0,research_quality_score=0,qmt=dict(open=10,lastPrice=11,lastClose=10,high=11,low=10,
                         amount=100000000+i*1000000,bidVol=[100],askVol=[100]),candidate=dict(score=None))
            if market=='HK_CONNECT':
                row.update(code=f'HK.{i+1:05}',open_price=10,last_price=11,high_price=11,low_price=10,
                           pct_chg=10,volume_ratio=2,turnover_hkd=100000000,
                           candidate_lanes=['D1_MODEL_TOP100'],circular_market_cap_hkd_yi=20)
            rows.append(row)
        return dict(market=market,target_date='20261008',stage_id='STAGE_0930_0935',
                    data_kind='SYNTHETIC',rows=rows,rows_sha256=sha256_json(rows),source_status='READY',
                    requested_rows=count,missing_symbols=[],cannot_confirm=[])
    def run_request(self,r):
        from v5_shadow.stage_selection import run_stage_selection
        return run_stage_selection(r)
    def test_a_original_live_formula_and_top10(self):
        r=self.request();original=copy.deepcopy(r);out=self.run_request(r)
        self.assertEqual(r,original);self.assertEqual(out['artifact']['source_rows'],12)
        self.assertEqual(out['artifact']['selected_rows'],10)
        self.assertEqual(out['artifact']['rows'][0]['source_mode'],'A_SHARE_WINDOWS_V3_LIVE_STAGE')
        self.assertEqual(out['artifact']['rows'][0]['score'],167.775)
        self.assertEqual([r['code'] for r in out['artifact']['rows']],[f'{i:06}' for i in range(12,2,-1)])
        self.assertIn('selection_contract=V3_TOP10_RECOMMENDATION',out['artifact']['source_evidence'])
        self.assertEqual(out['artifact']['algorithm_sha256'],out['expected_algorithm_sha256'])
        self.assertRegex(out['expected_algorithm_sha256'],r'^[0-9a-f]{64}$')
        self.assertFalse(out['natural_verified']);self.assertFalse(out['production_allowed'])
    def test_hk_original_four_lane_top10(self):
        r=self.request('HK_CONNECT');r['rows'][-1]['volume_ratio']=3;r['rows_sha256']=sha256_json(r['rows'])
        out=self.run_request(r)
        self.assertEqual(out['artifact']['source_rows'],12);self.assertEqual(out['artifact']['selected_rows'],10)
        self.assertEqual(out['artifact']['rows'][0]['source_mode'],'HK_CONNECT_FOUR_LANE')
        self.assertEqual([r['code'] for r in out['artifact']['rows']],['HK.00012']+[f'HK.{i:05}' for i in range(1,10)])
        self.assertEqual([r['score'] for r in out['artifact']['rows']],[93]+[89]*9)
        self.assertEqual(out['artifact']['algorithm_sha256'],out['expected_algorithm_sha256'])
    def test_wrong_digest_rejected(self):
        r=self.request();r['rows_sha256']='a'*64
        with self.assertRaises(ValueError):self.run_request(r)
    def test_future_row_time_rejected(self):
        r=self.request();r['rows'][0]['captured_at']='2026-10-08T09:36:00+08:00';r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaises(ValueError):self.run_request(r)
    def test_wrong_row_date_rejected(self):
        r=self.request();r['rows'][0]['trade_date']='20260930';r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaises(ValueError):self.run_request(r)
    def test_auction_not_silently_replaced(self):
        r=self.request();r['stage_id']='STAGE_0925'
        with self.assertRaisesRegex(ValueError,'STAGE_REQUIRES_SEPARATE_ORIGINAL_ROUTE'):self.run_request(r)
    def test_unknown_source_status_not_promoted(self):
        r=self.request();r['source_status']='UNKNOWN'
        with self.assertRaises(ValueError):self.run_request(r)
    def test_partial_coverage_preserved(self):
        r=self.request();r['requested_rows']=20
        out=self.run_request(r);self.assertEqual(out['artifact']['selection_status'],'PARTIAL_WITH_ROWS')
    def test_empty_evidence_explicit(self):
        r=self.request(count=0);r['source_status']='READY_EMPTY'
        self.assertEqual(self.run_request(r)['artifact']['selection_status'],'READY_EMPTY')
    def test_missing_research_not_silently_zeroed(self):
        r=self.request();del r['rows'][0]['news_quality_score'];r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaises(ValueError):self.run_request(r)
    def test_stage8_requires_separate_replay_gate(self):
        r=self.request('HK_CONNECT');r['stage_id']='STAGE_1545_1555'
        with self.assertRaisesRegex(ValueError,'STAGE_REQUIRES_SEPARATE_ORIGINAL_ROUTE'):self.run_request(r)
    def test_code_whitespace_cannot_hide_duplicate(self):
        r=self.request();r['rows'][1]['code']=' '+r['rows'][0]['code']+' ';r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaisesRegex(ValueError,'STAGE_CODE_INVALID_OR_DUPLICATE'):self.run_request(r)
    def test_invalid_priority_hk_alias_rejected(self):
        r=self.request('HK_CONNECT');r['rows'][0]['turnover_hkd_yi']='bad';r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaisesRegex(ValueError,'STAGE_REQUIRED_QUOTE_INVALID'):self.run_request(r)
    def test_hk_raw_score_override_rejected(self):
        r=self.request('HK_CONNECT');r['rows'][0]['stage_score']=999;r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaisesRegex(ValueError,'STAGE_HK_SCORE_OVERRIDE_NOT_SUPPORTED'):self.run_request(r)
    def test_negative_preferred_market_cap_rejected(self):
        r=self.request('HK_CONNECT');r['rows'][0]['platform_circular_market_cap_hkd_yi']=-1;r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaisesRegex(ValueError,'STAGE_HK_QUOTE_NEGATIVE'):self.run_request(r)
    def test_future_display_source_time_rejected(self):
        r=self.request('HK_CONNECT');r['rows'][0]['update_time']='2026-10-09T09:30:00+08:00';r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaisesRegex(ValueError,'STAGE_SOURCE_TIME_INVALID'):self.run_request(r)
    def test_incomplete_a_quote_rejected(self):
        r=self.request();del r['rows'][0]['qmt']['lastClose'];r['rows_sha256']=sha256_json(r['rows'])
        with self.assertRaises(ValueError):self.run_request(r)

if __name__=='__main__':unittest.main()
