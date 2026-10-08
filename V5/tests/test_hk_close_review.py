import copy
import json
import unittest
from v5_shadow.digests import sha256_json

STAGES=['STAGE_0925','STAGE_0930_0935','STAGE_0935_0940','STAGE_0940_0945','STAGE_0945_1030','STAGE_1300_1315','STAGE_1445_1500']
class HKCloseReviewTests(unittest.TestCase):
    def request(self):
        close=[dict(code=f'HK.{i:05}',trade_date='20261008',close=10+i/100,pre_close=10,amount=1000000,name=f'SYNTHETIC_{i}') for i in range(1,601)]
        model=[dict(symbol=f'HK.{i:05}',target_date='20261008',market='HK',pool_rank=n) for n,i in enumerate(range(600,500,-1),1)]
        stages={s:[dict(code='HK.00600',trade_date='20261008',stage_id=s,market='HK')] for s in STAGES}
        inputs=dict(close_rows=close,model_rows=model,stage_rows=stages,universe_codes=[r['code'] for r in close])
        return dict(target_date='20261008',data_kind='SYNTHETIC',captured_at='2026-10-08T16:10:00+08:00',
                    available_at='2026-10-08T16:11:00+08:00',research_cutoff='2026-10-08T17:00:00+08:00',
                    inputs=inputs,inputs_sha256=sha256_json(inputs))
    def run_request(self,r):
        from v5_shadow.hk_close_review import run_hk_close_review
        return run_hk_close_review(r)
    def refresh(self,r):r['inputs_sha256']=sha256_json(r['inputs']);return r
    def test_full_universe_original_top20_and_coverage(self):
        r=self.request();before=copy.deepcopy(r);out=self.run_request(r);a=out['artifact']
        self.assertEqual(r,before);self.assertEqual([v['code'] for v in a['close_top20']],[f'HK.{i:05}' for i in range(600,580,-1)])
        self.assertEqual(a['models']['0.2_prob_active']['hit_count'],20)
        self.assertEqual(a['stage_union']['hit_count'],1);self.assertEqual(a['stage_union']['coverage'],0.05)
        self.assertFalse(out['natural_verified']);self.assertFalse(out['input_provenance_verified'])
        self.assertNotEqual(a['evidence_mode'],'V3_5_NATIVE_PRODUCTION')
        self.assertEqual(a['status'],'CANNOT_CONFIRM');self.assertEqual(a['legacy_status'],'MODEL_REVIEW_READY')
        self.assertIn('PIT_AVAILABILITY_NOT_VERIFIED',a['cannot_confirm'])
    def test20_rows_not_full_market(self):
        r=self.request();r['inputs']['close_rows']=r['inputs']['close_rows'][:20]
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_UNIVERSE_INCOMPLETE'):self.run_request(self.refresh(r))
    def test_pre1610_source_rejected(self):
        r=self.request();r['captured_at']='2026-10-08T16:08:00+08:00'
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_BEFORE_FINAL_CUTOFF'):self.run_request(r)
    def test_missing_stage_stays_missing_not_zero(self):
        r=self.request();r['inputs']['stage_rows'][STAGES[0]]=None
        a=self.run_request(self.refresh(r))['artifact'];self.assertIsNone(a['stage_union']['hit_count'])
        self.assertEqual(a['missing_stages'],[STAGES[0]])
        self.assertTrue(all(r['stage_union_hit'] is None and r['classification']=='CANNOT_CONFIRM' for r in a['top20_attribution']))
    def test_stage8_cannot_replace_review_stages(self):
        r=self.request();r['inputs']['stage_rows']['STAGE_1545_1555']=[]
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_STAGE_SET_INVALID'):self.run_request(self.refresh(r))
    def test_foreign_day_stage_rejected(self):
        r=self.request();r['inputs']['stage_rows'][STAGES[0]][0]['trade_date']='20260930'
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_ROW_IDENTITY'):self.run_request(self.refresh(r))
    def test_duplicate_close_rejected(self):
        r=self.request();r['inputs']['close_rows'][1]['code']='HK.00001'
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_UNIVERSE_INCOMPLETE'):self.run_request(self.refresh(r))
    def test_missing_prevclose_not_silently_dropped(self):
        r=self.request();del r['inputs']['close_rows'][0]['pre_close']
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_PRICE_INVALID'):self.run_request(self.refresh(r))
    def test_changed_digest_rejected(self):
        r=self.request();r['inputs_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_INPUT_DIGEST'):self.run_request(r)
    def test_incomplete_model_remains_explicit(self):
        r=self.request();r['inputs']['model_rows']=r['inputs']['model_rows'][:99]
        a=self.run_request(self.refresh(r))['artifact'];self.assertIsNone(a['models']['0.2_prob_active']['hit_count'])
        self.assertEqual(a['legacy_status'],'MODEL_0_2_SOURCE_MISSING');self.assertEqual(a['status'],'CANNOT_CONFIRM')
        self.assertTrue(all(r['model_0_2_hit'] is None and r['classification']=='CANNOT_CONFIRM' for r in a['top20_attribution']))

    def test_empty_stage_is_declared_not_verified_empty(self):
        r=self.request();r['inputs']['stage_rows'][STAGES[0]]=[]
        a=self.run_request(self.refresh(r))['artifact']
        self.assertEqual(a['input_evidence']['stages'][STAGES[0]]['input_state'],'DECLARED_EMPTY')
        self.assertFalse(a['input_evidence']['authoritative_inputs_bound'])
    def test_half_day_afternoon_rows_rejected(self):
        r=json.loads(json.dumps(self.request()).replace('20261008','20261224').replace('2026-10-08','2026-12-24'))
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_AFTER_HALF_DAY_STAGE'):self.run_request(self.refresh(r))
    def test_599_universe_not_full_market(self):
        r=self.request();r['inputs']['universe_codes']=r['inputs']['universe_codes'][:-1];r['inputs']['close_rows']=r['inputs']['close_rows'][:-1]
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_UNIVERSE_INCOMPLETE'):self.run_request(self.refresh(r))
    def test101_model_rows_rejected(self):
        r=self.request();r['inputs']['model_rows'].append(dict(r['inputs']['model_rows'][0]))
        with self.assertRaisesRegex(ValueError,'HK_CLOSE_MODEL_INVALID'):self.run_request(self.refresh(r))

if __name__=='__main__':unittest.main()
