"""Price-storage parity regression for the configured legacy owner, no market/labels."""
from pathlib import Path
import importlib.util,sys,unittest,tempfile
import numpy as np
import pandas as pd
sys.dont_write_bytecode=True
PATH=Path(__file__).resolve().parents[1]/'runtime/v1/data_layer_daily_formula_increment_update_v1.py'
spec=importlib.util.spec_from_file_location('legacy_boundary_owner_frozen_test',PATH)
owner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=owner;spec.loader.exec_module(owner)

def frames(dtype,stored=2459.87,generated=2459.87,source='tdx_day_raw_previous_close'):
 current=pd.DataFrame({'ts_code':['688808.SH'],'trade_date':[20260911],'close':np.array([stored],dtype=dtype)})
 increment=pd.DataFrame({'ts_code':['688808.SH'],'trade_date':[20260914],'close':[2411.98],'pre_close':[generated],'pct_chg_source':[source]})
 return current,increment
class StorageBoundaryTests(unittest.TestCase):
 def test_same_native_cent_price_survives_float32_storage(self):
  current,increment=frames(np.float32)
  self.assertEqual(owner.audit_increment_boundary(current,increment)['status'],'PASS')
 def test_same_native_cent_price_float64_passes(self):
  current,increment=frames(np.float64)
  self.assertEqual(owner.audit_increment_boundary(current,increment)['status'],'PASS')
 def test_real_one_cent_discontinuity_still_blocks_both_dtypes(self):
  for dtype in [np.float32,np.float64]:
   with self.subTest(dtype=str(dtype)):
    current,increment=frames(dtype,generated=2459.88)
    self.assertEqual(owner.audit_increment_boundary(current,increment)['status'],'BLOCKED_INCREMENT_BOUNDARY_DISCONTINUITY')
 def test_large_real_boundary_still_blocks(self):
  current,increment=frames(np.float32,stored=4.35,generated=2.85)
  self.assertEqual(owner.audit_increment_boundary(current,increment)['bad_symbols'],['688808.SH'])
 def test_missing_preclose_still_blocks(self):
  current,increment=frames(np.float32,generated=np.nan)
  self.assertEqual(owner.audit_increment_boundary(current,increment)['bad_keys'][0]['reason'],'PRE_CLOSE_MISSING')
 def test_xdxr_exemption_policy_and_inputs_unchanged(self):
  current,increment=frames(np.float32,stored=4.35,generated=2.85,source='tdx_xdxr_adjusted_previous_close');a=current.copy(deep=True);b=increment.copy(deep=True)
  self.assertEqual(owner.audit_increment_boundary(current,increment)['status'],'PASS_WITH_XDXR_EXEMPTION')
  pd.testing.assert_frame_equal(current,a);pd.testing.assert_frame_equal(increment,b)
 def test_storage_only_difference_does_not_isolate_other_role(self):
  a,ia=frames(np.float64);b,ib=frames(np.float32)
  def add_healthy(current,increment):
   healthy=pd.DataFrame({'ts_code':['600000.SH'],'trade_date':[20260911],'close':np.array([10.0],dtype=current['close'].dtype)})
   healthy_inc=pd.DataFrame({'ts_code':['600000.SH'],'trade_date':[20260914],'close':[10.1],'pre_close':[10.0],'pct_chg_source':['tdx_day_raw_previous_close']})
   return pd.concat([current,healthy],ignore_index=True),pd.concat([increment,healthy_inc],ignore_index=True)
  a,ia=add_healthy(a,ia);b,ib=add_healthy(b,ib)
  result=owner.isolate_increment_boundary_bad_symbols({'selector':a,'backtest':b},{'selector':ia,'backtest':ib},target_date=20260914)
  self.assertEqual(result['bad_symbols'],[])
  self.assertEqual(result['isolation_by_role']['selector']['remaining_row_count'],2)
  self.assertEqual(result['isolation_by_role']['backtest']['remaining_row_count'],2)
class ExplicitKeyRepairTests(unittest.TestCase):
 def setUp(self):
  import pyarrow as pa
  self.pa=pa
  root=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_quarantine_recovery_20261021/key_repair_test_staging')
  root.mkdir(exist_ok=True)
  self.temporary=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temporary.cleanup)
  self.root=Path(self.temporary.name);self.current=self.root/'current.parquet';self.output=self.root/'repaired.parquet'
  self.schema=pa.schema([('ts_code',pa.dictionary(pa.int32(),pa.string())),('trade_date',pa.int32()),('close',pa.float32()),('optional_note',pa.string()),('flag',pa.bool_())])
  self.rows=[{'ts_code':'600228.SH','trade_date':20250717,'close':9.81,'optional_note':None,'flag':False},
    {'ts_code':'600228.SH','trade_date':20260608,'close':2.54,'optional_note':'retire','flag':True},
    {'ts_code':'600228.SH','trade_date':20260625,'close':2.54,'optional_note':'replace','flag':False},
    {'ts_code':'600000.SH','trade_date':20261021,'close':12.345678,'optional_note':'unaffected','flag':True}]
  self.log=type('QuietLogger',(),{'log':lambda self,message:None})()
 def table(self,rows):return self.pa.Table.from_pylist(rows,schema=self.schema)
 def stage_input(self,rows=None):owner.pq.write_table(self.table(self.rows if rows is None else rows),self.current)
 def run_repair(self,new,retired):return owner.write_appended_parquet(self.current,self.table(new),self.output,self.log,retire_keys=retired)
 def test_exact_retire_replace_insert_and_unaffected_values(self):
  self.stage_input();before=owner.pq.read_table(self.current);new=[dict(self.rows[2],close=9.81,optional_note='verified'),dict(self.rows[2],trade_date=20261021,close=10.5)]
  receipt=self.run_repair(new,[('600228.SH',20260608)])
  actual=owner.pq.read_table(self.output)
  expected=self.table([before.to_pylist()[0],before.to_pylist()[3]]+new)
  self.assertTrue(actual.schema.equals(expected.schema));self.assertEqual(actual.to_pylist(),expected.to_pylist());self.assertTrue(owner.pq.read_table(self.current).equals(before))
  self.assertEqual((receipt['current_rows_retained'],receipt['current_rows_replaced'],receipt['current_rows_retired'],receipt['new_rows_inserted'],receipt['total_rows_expected']),(2,1,1,1,4))
 def test_retire_only_is_supported(self):
  self.stage_input();receipt=self.run_repair([],[('600228.SH',20260608)])
  self.assertEqual(owner.pq.read_table(self.output).num_rows,3);self.assertEqual(receipt['current_rows_retired'],1)
 def test_duplicate_new_and_retire_keys_rejected(self):
  self.stage_input()
  for new,retired in [([self.rows[2],self.rows[2]],[]),([],[('600228.SH',20260608),('600228.SH',20260608)])]:
   with self.subTest(new=new,retired=retired):
    with self.assertRaisesRegex(RuntimeError,'duplicate'):self.run_repair(new,retired)
    self.assertFalse(self.output.exists())
 def test_duplicate_current_not_silently_deduplicated(self):
  self.stage_input(self.rows+[self.rows[3]])
  with self.assertRaisesRegex(RuntimeError,'duplicate current'):self.run_repair([],[('600228.SH',20260608)])
  self.assertFalse(self.output.exists());self.assertEqual(owner.pq.read_table(self.current).num_rows,5)
 def test_missing_retire_key_rejected(self):
  self.stage_input()
  with self.assertRaisesRegex(RuntimeError,'absent'):self.run_repair([],[('600228.SH',20260609)])
  self.assertFalse(self.output.exists())
 def test_retire_new_key_conflict_rejected(self):
  self.stage_input()
  with self.assertRaisesRegex(RuntimeError,'conflicts'):self.run_repair([self.rows[2]],[('600228.SH',20260625)])
  self.assertFalse(self.output.exists())
 def test_existing_output_and_schema_mismatch_rejected(self):
  self.stage_input();self.output.write_bytes(b'preserve existing output')
  with self.assertRaisesRegex(RuntimeError,'already exists'):self.run_repair([],[])
  self.assertEqual(self.output.read_bytes(),b'preserve existing output')
  self.output.unlink()
  wrong=self.table([]).drop(['flag'])
  with self.assertRaisesRegex(RuntimeError,'schema'):owner.write_appended_parquet(self.current,wrong,self.output,self.log,retire_keys=[])
  self.assertFalse(self.output.exists())
if __name__=='__main__':unittest.main()
