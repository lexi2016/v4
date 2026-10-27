import unittest,importlib.util,datetime
from pathlib import Path
class FormulaTests(unittest.TestCase):
 def engine(self):
  self.assertIsNotNone(importlib.util.find_spec('formula_engine'),'formula_engine implementation is missing')
  import formula_engine
  return formula_engine
 def bars(self,n=130):
  start=datetime.date(2025,1,1)
  return [dict(trade_date=int((start+datetime.timedelta(days=i)).strftime('%Y%m%d')),open=10+i/100,high=11+i/100,low=9+i/100,close=10+i/100,vol=100+i,amount=1000) for i in range(n)]
 def test_exact_source_inventory(self):
  e=self.engine();p=e.inventory();self.assertEqual(p['source_sha256'],'d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac');self.assertEqual(len(p['assignments']),51);self.assertEqual(len(p['drawings']),22)
 def test_reference_and_full_window(self):
  e=self.engine();b=self.bars(4);self.assertEqual(e.expression('REF(CLOSE,1)',b),[None,e.D('10.0'),e.D('10.01'),e.D('10.02')]);self.assertEqual(e.expression('MA(CLOSE,3)',b)[:2],[None,None]);self.assertEqual(e.expression('MA(CLOSE,3)',b)[2],e.D('10.01'))
 def test_ema_sma_seed_and_recursive(self):
  e=self.engine();b=self.bars(3)
  self.assertEqual(e.expression('EMA(CLOSE,3)',b),[e.D('10'),e.D('10.005'),e.D('10.0125')]);self.assertEqual(e.expression('SMA(CLOSE,3,1)',b)[0],e.D('10'))
 def test_cross_and_barslast_unknown_zero_count(self):
  e=self.engine();b=self.bars(4);v={'A':[e.D(0),e.D(1),e.D(2),e.D(1)],'B':[e.D(1)]*4}
  self.assertEqual(e.expression('CROSS(A,B)',b,v),[None,False,True,False]);self.assertEqual(e.expression('BARSLAST(A>B)',b,v),[None,None,e.D(0),e.D(1)]);self.assertEqual(e.expression('COUNT(A>B,0)',b,v),[e.D(0),e.D(0),e.D(1),e.D(1)])
 def test_unknown_count_and_logic_contract(self):
  e=self.engine();b=self.bars(3);v={'A':[None,False,True]}
  self.assertEqual(e.expression('COUNT(A,2)',b,v),[None,None,e.D(1)])
  self.assertEqual(e.expression('A AND 0',b,v),[None,False,False]);self.assertEqual(e.expression('A OR 1',b,v),[None,True,True])
 def test_zero_denominator_not_false_signal(self):
  e=self.engine();b=[dict(x,high=10,low=10,open=10,close=10) for x in self.bars(130)];r=e.compute(b)['rows'];self.assertIsNone(r[-1]['values']['RSV']);self.assertIsNone(r[-1]['values']['J']);self.assertIsNone(r[-1]['values']['B1'])
 def test_full_output_bbi_yellow_and_endpoint(self):
  e=self.engine();b=self.bars();p=e.compute(b);r=p['rows'];self.assertEqual(len(r[-1]['values']),51);self.assertEqual(len(r[-1]['drawings']),22);self.assertTrue(all(x['values']['今天'] is True for x in r));a=e.compute(b,mode='asof')['rows'];self.assertFalse(a[-2]['values']['今天']);self.assertTrue(a[-1]['values']['今天']);self.assertEqual(r[-1]['values'],a[-1]['values'])
  cs=[e.D(str(x['close'])) for x in b];expected=sum(sum(cs[-k:])/k for k in [14,28,57,114])/4;self.assertEqual(r[-1]['values']['黄线'],expected)
 def test_invalid_order_nonfinite_rejected(self):
  e=self.engine();b=self.bars(3)
  for bad in [b[::-1],[b[0],b[0]], [dict(b[0],close=float('nan'))]]:
   with self.assertRaises(ValueError):e.compute(bad)
 def test_exact_eight_digit_date_and_ohlc_range(self):
  e=self.engine();b=self.bars(1)
  for bad in [dict(b[0],trade_date=2026111),dict(b[0],close=12),dict(b[0],open=8)]:
   with self.assertRaises(ValueError):e.compute([bad])
 def test_empty_input_rejected(self):
  e=self.engine()
  with self.assertRaisesRegex(ValueError,'EMPTY_HISTORY'):e.compute([])
 def test_prefix_append_invariance(self):
  e=self.engine();b=self.bars(130);short=e.compute(b[:120])['rows'];long=e.compute(b)['rows'];self.assertEqual(short,long[:120])
 def test_unrecognized_code_not_executed(self):
  e=self.engine()
  with self.assertRaises(ValueError):e.expression('__import__(123)',self.bars(1))
 def test_missing_calendar_day_not_synthetic_bar(self):
  e=self.engine();b=self.bars(5);b.pop(2);r=e.compute(b)['rows'];self.assertEqual(len(r),4);self.assertEqual([x['trade_date'] for x in r],[x['trade_date'] for x in b])
if __name__=='__main__':unittest.main()
