import copy
import unittest
from v5_shadow.digests import sha256_json

class ACloseReviewTests(unittest.TestCase):
    def request(self):
        rows=[dict(trade_date='20261008',ts_code=f'{i:06}.SZ',name=f'SYNTHETIC_{i}',pct_chg=pct,amount=100000000,
                   bar_close_pos=0.8,tdx_industry_code='I1' if i<3 else 'I2',tdx_industry_name='甲行业' if i<3 else '乙行业')
              for i,pct in enumerate((10,2,-10,-1),1)]
        return dict(target_date='20261008',data_kind='SYNTHETIC',captured_at='2026-10-08T15:30:00+08:00',
                    available_at='2026-10-08T15:31:00+08:00',research_cutoff='2026-10-08T16:00:00+08:00',
                    rows=rows,rows_sha256=sha256_json(rows),universe_codes=[r['ts_code'] for r in rows])
    def run_request(self,r):
        from v5_shadow.a_close_review import run_a_close_review
        return run_a_close_review(r)
    def refresh(self,r):r['rows_sha256']=sha256_json(r['rows']);return r
    def test_original_summary_and_explicit_boundaries(self):
        r=self.request();before=copy.deepcopy(r);out=self.run_request(r);a=out['artifact']
        self.assertEqual(r,before);self.assertEqual(a['market_summary']['up_count'],2);self.assertEqual(a['market_summary']['down_count'],2)
        self.assertEqual(a['market_summary']['market_width'],0.5);self.assertEqual(a['market_summary']['amount_yi'],4)
        self.assertEqual(a['visibility_stage'],'POST_CLOSE_REVIEW_ONLY');self.assertFalse(out['input_provenance_verified'])
        self.assertEqual(a['status'],'CANNOT_CONFIRM');self.assertFalse(a['strict_1500_pit_verified'])
        self.assertEqual(a['scenario_probabilities_status'],'FROZEN_LEGACY_CONSTANTS_NOT_CALIBRATED')
    def test_preclose_rejected(self):
        r=self.request();r['captured_at']='2026-10-08T14:59:00+08:00'
        with self.assertRaisesRegex(ValueError,'A_CLOSE_BEFORE_POST_CLOSE'):self.run_request(r)
    def test_missing_industry_not_filled(self):
        r=self.request();del r['rows'][0]['tdx_industry_name']
        with self.assertRaisesRegex(ValueError,'A_CLOSE_FIELDS_MISSING'):self.run_request(self.refresh(r))
    def test_invalid_price_change_not_dropped(self):
        r=self.request();r['rows'][0]['pct_chg']='bad'
        with self.assertRaisesRegex(ValueError,'A_CLOSE_NUMBER_INVALID'):self.run_request(self.refresh(r))
    def test_duplicate_code_rejected(self):
        r=self.request();r['rows'][1]['ts_code']=r['rows'][0]['ts_code']
        with self.assertRaisesRegex(ValueError,'A_CLOSE_UNIVERSE_MISMATCH'):self.run_request(self.refresh(r))
    def test_wrong_day_rows_rejected(self):
        r=self.request();r['rows'][0]['trade_date']='20260930'
        with self.assertRaisesRegex(ValueError,'A_CLOSE_ROW_DATE'):self.run_request(self.refresh(r))
    def test_changed_digest_rejected(self):
        r=self.request();r['rows_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'A_CLOSE_INPUT_DIGEST'):self.run_request(r)
    def test_closed_market_rejected(self):
        r=self.request();r['target_date']='20261007'
        for row in r['rows']:row['trade_date']='20261007'
        for k in ('captured_at','available_at','research_cutoff'):r[k]=r[k].replace('10-08','10-07')
        with self.assertRaisesRegex(ValueError,'A_CLOSE_MARKET_NOT_OPEN'):self.run_request(self.refresh(r))

    def test_actual_capture_distinct_from_frozen_label(self):
        r=self.request();r['captured_at']='2026-10-08T15:45:00+08:00';r['available_at']='2026-10-08T15:46:00+08:00'
        a=self.run_request(r)['artifact'];self.assertEqual(a['as_of'],r['captured_at'])
        self.assertEqual(a['legacy_as_of'],'2026-10-08T15:30:00+08:00');self.assertEqual(a['research_cutoff'],r['research_cutoff'])

if __name__=='__main__':unittest.main()
