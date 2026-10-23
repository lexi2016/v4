"""Focused adapter regressions; no model fit or price/source writes."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import data194 as d

class Data194Tests(unittest.TestCase):
    def test_entire_body_not_first_hundred(self):
        self.assertFalse(d.full_text_bound('x'*100+'wrong', 'x'*100+'right'))
        self.assertTrue(d.full_text_bound('<b>原文</b> 全部', '前缀原文\n全部后缀'))
        self.assertFalse(d.full_text_bound('', '正文'))

    def test_native_status_tuple_sha_is_not_path(self):
        auth=('2026-10-22T09:00:00+08:00', {'status_path':'owned/status.json'}, 'a'*64, False)
        _,_,path,sha,declared=d.status_binding(auth)
        self.assertEqual(path,'owned/status.json')
        self.assertEqual(sha,'a'*64)
        self.assertFalse(declared)

    def test_timezone_unknown_rejected(self):
        with self.assertRaisesRegex(ValueError,'TIMEZONE_UNPROVEN'):d.aware('2026-10-22T09:00:00')
        self.assertIsNotNone(d.aware('2026-10-22T09:00:00+08:00').utcoffset())

    def test_stock_identity_not_index_or_foreign(self):
        self.assertEqual(d.keycode('A.000001'),'000001')
        self.assertEqual(d.keycode('920003.BJ'),'920003')
        self.assertIsNone(d.keycode('HK.00001'))

    def test_full_technical_schema(self):
        self.assertEqual(len(d.TECH),11)
        self.assertEqual(len(set(d.TECH)),11)
        self.assertEqual(d.TECH[0],'tech_192')
        self.assertIn('BRICK_FANBAO',d.TECH)
        self.assertEqual(d.SOURCES,['source_fupan','source_stage7','source_research'])

class Data194PolicyFixTests(unittest.TestCase):
    def test_valid_close_zero_target_volume_has_return(self):
        import numpy as np
        fields=['open','high','low','close','volume','amount']
        raw={f:np.array([10.,11.]) for f in fields};raw['volume']=np.array([100.,0.])
        engine=SimpleNamespace(FIELDS=fields,reconstruct=lambda *args:(['20260803','20260804'],raw,[],[],[]),project=lambda dates,values,events,anchor:values)
        original=SimpleNamespace(evaluate=lambda program,values,code:{'XG':np.zeros(len(values['C']))})
        kernel=SimpleNamespace(Engine=lambda columns:object(),RULES={})
        task=('000001.SZ',{'status':'READY','name':'SYNTH'},[],{}, {},{},None,[('20260803','20260804')])
        with patch.object(d,'engines',return_value=(engine,{},original,kernel,None)):result=d.compute_stock(task)
        self.assertEqual(len(result['truth']),1)
        self.assertAlmostEqual(result['truth'][0]['return'],0.1)

    def test_unknown_label_excludes_whole_date_without_deleting_rows(self):
        calendar=[{'target_date':'2026-08-03','cohort_role':'eligible'}, {'target_date':'2026-08-04','cohort_role':'eligible'}, {'target_date':'2026-10-19','cohort_role':'diagnostic'}, {'target_date':'2026-10-23','cohort_role':'unlabelled_prediction'}]
        candidates=[('2026-08-03','A'),('2026-08-04','A'),('2026-08-04','B'),('2026-10-19','A'),('2026-10-23','A')]
        revised,policy=d.freeze_date_policy(calendar,candidates,{('2026-08-03','A'),('2026-08-04','A')},['2026-08-03'])
        self.assertEqual(len(candidates),5)
        self.assertEqual(calendar[1]['cohort_role'],'eligible')
        self.assertEqual(revised[1]['cohort_role'],'excluded_incomplete_truth')
        self.assertEqual(revised[2]['cohort_role'],'diagnostic')
        self.assertEqual(revised[3]['cohort_role'],'unlabelled_prediction')
        self.assertEqual(policy['all_incomplete_target_dates'],['2026-08-04','2026-10-19'])
        self.assertEqual(policy['exclusions'],[dict(target_date='2026-08-04',reason='INCOMPLETE_CANDIDATE_TRUTH_WHOLE_DATE_EXCLUDED',unknown_candidate_label_rows=1,training_eligible=False)])
        self.assertFalse(policy['total_date_gate_met'])
        with self.assertRaisesRegex(ValueError,'REVIEWER_FROZEN_DATE_ARRAY_MISMATCH'):d.freeze_date_policy(calendar,candidates,set(),['2026-08-03'])

    def test_35_dates_split17_18_cannot_pass_effect_date_gate(self):
        from datetime import date,timedelta
        dates=[(date(2026,7,1)+timedelta(days=i)).isoformat() for i in range(35)]
        calendar=[dict(target_date=dt,cohort_role='eligible') for dt in dates];keys={(dt,'SYNTH') for dt in dates}
        _,policy=d.freeze_date_policy(calendar,keys,keys,dates)
        self.assertEqual(len(policy['initial_train_target_dates']),17)
        self.assertEqual([len(f) for f in policy['oof_date_folds']],[5,5,5,3])
        self.assertEqual(len(policy['oof_target_dates']),18)
        self.assertTrue(policy['total_date_gate_met'])
        self.assertFalse(policy['effect_date_gate_met'])
        self.assertEqual(policy['effect_acceptance_ceiling'],'CANNOT_CONFIRM_INSUFFICIENT_OOF_DATES')

if __name__=='__main__':unittest.main()
