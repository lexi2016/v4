import unittest,importlib.util,json,gzip,copy,hashlib
from pathlib import Path
H=Path(__file__).resolve().parent;s=importlib.util.spec_from_file_location('state_bootstrap_test',H/'state_engine.py');E=importlib.util.module_from_spec(s);s.loader.exec_module(E)
R=H.parents[3];P=H.parent/'canary002608_output/stocks/002608.SZ/formula.json.gz';ALL=json.loads(gzip.decompress(P.read_bytes()))['rows'][:-1]
def binding(rows):
 return {'symbol':'002608.SZ','purpose':'SIX_STOCK_CACHED_HOLDOUT_ALGORITHM_ONLY','price_coordinate':'FIXED_VINTAGE_QFQ_NONPIT','event_sha256':'e'*64,'policy_sha256':'a'*64,'source_formula_sha256':hashlib.sha256(P.read_bytes()).hexdigest(),'volume_contract_sha256':'b'*64,'bootstrap_prefix_sha256':hashlib.sha256(E.canonical(rows)).hexdigest(),'date_contract':{'kind':'CACHED_ADJACENT_SEQUENCE_ONLY_NOT_CALENDAR_ADMITTED','open_dates':[r['trade_date']for r in ALL]}}
class TestBootstrapStep(unittest.TestCase):
 def ready(self):self.assertTrue(hasattr(E,'bootstrap')and hasattr(E,'step'),'bootstrap/step absent')
 def test_real_one_day_exact_and_no_old_mutation(self):
  self.ready();rows=copy.deepcopy(ALL[:-1]);before=E.canonical(rows);b=binding(rows);st=E.bootstrap('002608.SZ',rows,rows[-1]['trade_date'],b);out,new=E.step(st,ALL[-1]['ohlcv'],b);self.assertEqual(out,ALL[-1]);self.assertEqual(E.canonical(rows),before);self.assertEqual(st['last_date'],rows[-1]['trade_date']);self.assertEqual(new['last_date'],ALL[-1]['trade_date'])
 def test_prefix_cutoff_future_rows_rejected(self):
  self.ready()
  with self.assertRaises(ValueError):E.bootstrap('002608.SZ',ALL,ALL[-2]['trade_date'],binding(ALL))
 def test_changed_event_binding_rejected(self):
  self.ready();rows=ALL[:-1];b=binding(rows);st=E.bootstrap('002608.SZ',rows,rows[-1]['trade_date'],b);bad=copy.deepcopy(b);bad['event_sha256']='f'*64
  with self.assertRaises(ValueError):E.step(st,ALL[-1]['ohlcv'],bad)
 def test_missing_or_tampered_state_rejected(self):
  self.ready();rows=ALL[:-1];b=binding(rows);st=E.bootstrap('002608.SZ',rows,rows[-1]['trade_date'],b);del st['nodes'][next(iter(st['nodes']))]
  with self.assertRaises(ValueError):E.step(st,ALL[-1]['ohlcv'],b)
 def test_duplicate_day_rejected(self):
  self.ready();b=binding(ALL);st=E.bootstrap('002608.SZ',ALL,ALL[-1]['trade_date'],b)
  with self.assertRaises(ValueError):E.step(st,ALL[-1]['ohlcv'],b)
if __name__=='__main__':unittest.main(verbosity=2)

class TestCalendarAuthority(unittest.TestCase):
 def test_claimed_verified_calendar_with_fake_hash_rejected(self):
  rows=ALL[:-1];b=binding(rows);b['date_contract']={'kind':'VERIFIED_CALENDAR_RESEARCH_CANDIDATE','open_dates':[20261023,20261026],'coverage_start':'20261023','coverage_end':'20261231','calendar_sha256':'0'*64}
  with self.assertRaises(ValueError):E.bootstrap('002608.SZ',rows,rows[-1]['trade_date'],b)

class TestNodeSchema(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.rows=ALL[:-1];cls.b=binding(cls.rows);cls.state=E.bootstrap('002608.SZ',cls.rows,cls.rows[-1]['trade_date'],cls.b)
 def test_every_required_node_field_missing_resealed_rejected(self):
  for key,node in self.state['nodes'].items():
   for field in set(node)-{'kind'}:
    with self.subTest(kind=node['kind'],field=field):
     bad=copy.deepcopy(self.state);del bad['nodes'][key][field]
     with self.assertRaises(ValueError):E.step(E.seal(bad),ALL[-1]['ohlcv'],self.b)
 def test_invalid_counter_buffer_and_hidden_null_rejected(self):
  for key,node in self.state['nodes'].items():
   for field in set(node)-{'kind'}:
    value=[] if field=='buffer' else ['NaN',None] if field=='previous' else -1 if field in ('known','true','last_true','age','since_true','since_null','anchor_index') else 'NaN'
    with self.subTest(kind=node['kind'],field=field):
     bad=copy.deepcopy(self.state);bad['nodes'][key][field]=value
     with self.assertRaises(ValueError):E.step(E.seal(bad),ALL[-1]['ohlcv'],self.b)
  for key in E.inventory()[-1]:
   bad=copy.deepcopy(self.state);bad['nodes'][key]['value']=None
   with self.assertRaises(ValueError):E.step(E.seal(bad),ALL[-1]['ohlcv'],self.b)

class TestContextAndCalendarContent(unittest.TestCase):
 def test_rounding_caller_does_not_change_step(self):
  from decimal import localcontext,ROUND_DOWN
  rows=ALL[:-1];b=binding(rows);st=E.bootstrap('002608.SZ',rows,rows[-1]['trade_date'],b)
  with localcontext() as ctx:
   ctx.rounding=ROUND_DOWN;out,new=E.step(st,ALL[-1]['ohlcv'],b)
  self.assertEqual(out,ALL[-1])
 def test_real_calendar_hash_cannot_certify_weekend(self):
  rows=ALL[:-1];b=binding(rows);cp=E.PROJECT/'daily_pipeline/CALENDAR_20261023_1231_VERIFIED_V2.json';cal=json.loads(cp.read_bytes());dates=[int(x)for x in cal['open_dates']];dates.insert(1,20261024)
  b['date_contract']={'kind':'VERIFIED_CALENDAR_RESEARCH_CANDIDATE','open_dates':dates,'coverage_start':cal['coverage_start'],'coverage_end':cal['coverage_end'],'calendar_sha256':hashlib.sha256(cp.read_bytes()).hexdigest()}
  with self.assertRaises(ValueError):E.bootstrap('002608.SZ',rows,rows[-1]['trade_date'],b)
