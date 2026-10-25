import unittest
import pandas as pd
from audit import *
class AuditEdges(unittest.TestCase):
 def truth(self):return top100(pd.DataFrame([dict(trade_date='20261023',ts_code=f'{i:06}.SZ',close=11,pre_close=10) for i in range(101)]))
 def test_tie_and_return(self):
  t=self.truth();self.assertEqual(t.iloc[0].ts_code,'000000.SZ');self.assertAlmostEqual(t.iloc[0].return_pct,10);self.assertEqual(t.iloc[100].daily_rank,101)
 def test_missing_not_zero(self):self.assertIsNone(cell_metrics(None,self.truth())['hit_count']);self.assertEqual(cell_metrics([],self.truth())['hit_count'],0)
 def test_actual_slots_membership(self):
  m=cell_metrics([{'code':'SZ.000000'},{'code':'SZ.000100'}],self.truth(),{'000000.SZ'});self.assertEqual(m['selection_slots'],2);self.assertEqual(m['hit_count'],1);self.assertEqual(m['hit_precision'],.5);self.assertEqual(m['truth_positive_denominator'],100);self.assertEqual(m['screen_retention'],1)
 def test_duplicates_fail(self):
  with self.assertRaisesRegex(ValueError,'DUPLICATE'):cell_metrics([{'code':'SZ.000001'},{'code':'000001.SZ'}],self.truth())
 def test_duplicate_truth_fails(self):
  with self.assertRaisesRegex(ValueError,'DUPLICATE'):top100(pd.DataFrame([dict(trade_date='1',ts_code='000001.SZ',close=1,pre_close=1)]*2))
 def test_bad_prices_excluded(self):
  t=top100(pd.DataFrame([dict(trade_date='1',ts_code='000001.SZ',close=1,pre_close=0)]));self.assertEqual(len(t),0)
if __name__=='__main__':unittest.main()
