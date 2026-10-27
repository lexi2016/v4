import unittest, struct
from data_engine import parse_day, classify, qfq_candidate
class DataTests(unittest.TestCase):
 def test_short(self):
  with self.assertRaises(ValueError):parse_day(b'x')
 def test_order(self):
  b=struct.pack('<5If2I',20261023,100,100,100,100,10.,10,0)
  with self.assertRaises(ValueError):parse_day(b+b)
 def test_identity(self):
  self.assertEqual(classify('sh000001.day'),'NON_A_SHARE')
  self.assertEqual(classify('sh600000.day'),'SH_A_CODE_CANDIDATE')
 def test_cash(self):
  bars=[dict(trade_date=20260101,open=10.,high=10.,low=10.,close=10.,vol=10,amount=100),dict(trade_date=20260102,open=9.,high=9.,low=9.,close=9.,vol=10,amount=90)]
  q,s=qfq_candidate(bars,[dict(date=20260102,category=1,c1=10.,c2=0.,c3=0.,c4=0.)],20261023)
  self.assertEqual(q[0]['close'],9.)
  self.assertEqual(q[-1]['close'],9.)
 def test_rights_block(self):
  q,s=qfq_candidate([dict(trade_date=20260101)], [dict(date=20260102,category=1,c1=0.,c2=10.,c3=0.,c4=3.)],20261023)
  self.assertIsNone(q);self.assertIn('RIGHTS_RATIO_UNVERIFIED',s)
 def test_special_block(self):
  q,s=qfq_candidate([dict(trade_date=20260101)],[dict(date=20260102,category=15,c1=0.,c2=0.,c3=0.,c4=0.)],20261023)
  self.assertIsNone(q);self.assertIn('SPECIAL_EVENT_15',s)
 def test_future_event(self):
  b=[dict(trade_date=20260101,open=10.,high=10.,low=10.,close=10.,vol=10,amount=100)]
  q,s=qfq_candidate(b,[dict(date=20270101,category=1,c1=10.,c2=0.,c3=0.,c4=0.)],20261023)
  self.assertEqual(q[0]['close'],10.)
if __name__=='__main__':unittest.main()
