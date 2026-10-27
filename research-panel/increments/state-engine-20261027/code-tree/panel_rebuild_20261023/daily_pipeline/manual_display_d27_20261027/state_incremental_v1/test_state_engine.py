import unittest,importlib.util,copy,json
from pathlib import Path
from decimal import Decimal as D,localcontext
H=Path(__file__).resolve().parent
S=None
if (H/'state_engine.py').exists():
 sp=importlib.util.spec_from_file_location('new_state_engine_test',H/'state_engine.py');S=importlib.util.module_from_spec(sp);sp.loader.exec_module(S)
class TestStateOperators(unittest.TestCase):
 def ready(self):self.assertIsNotNone(S,'state engine absent')
 def evals(self,expr,rows):
  self.ready();ast=S.F.Parser(expr).parse();nodes={};out=[]
  for i,env in enumerate(rows):
   with localcontext()as c:c.prec=28;out.append(S.Evaluator(i,nodes).evaluate(ast,env))
  return out
 def test_ema_preserves_state_across_null_emission(self):
  self.assertEqual(self.evals('EMA(X,3)',[{'X':D(2)},{'X':None},{'X':D(4)}]),[D(2),None,D(3)])
 def test_sma_exact_order(self):
  self.assertEqual(self.evals('SMA(X,3,1)',[{'X':D(2)},{'X':D(5)}]),[D(2),D(3)])
 def test_barslast_null_clears_old_true(self):
  self.assertEqual(self.evals('BARSLAST(X)',[{'X':True},{'X':False},{'X':None},{'X':False},{'X':True}]),[D(0),D(1),None,None,D(0)])
 def test_count_zero_means_whole_known_prefix(self):
  self.assertEqual(self.evals('COUNT(X,0)',[{'X':None},{'X':True},{'X':None},{'X':False}]),[None,D(1),D(1),D(1)])
 def test_fixed_count_null_window(self):
  self.assertEqual(self.evals('COUNT(X,2)',[{'X':True},{'X':None},{'X':False},{'X':True}]),[None,None,None,D(1)])
 def test_dynamic_count_boundary_zero_not_empty(self):
  rows=[{'X':True,'A':True},{'X':False,'A':False},{'X':True,'A':False},{'X':False,'A':True},{'X':None,'A':False}]
  self.assertEqual(self.evals('COUNT(X,BARSLAST(A))',rows),[D(1),D(0),D(1),D(2),None])
 def test_dynamic_ref_anchor_and_reset(self):
  rows=[{'X':D(10),'A':True},{'X':D(11),'A':False},{'X':D(12),'A':None},{'X':D(13),'A':False},{'X':D(14),'A':True}]
  self.assertEqual(self.evals('REF(X,BARSLAST(A))',rows),[D(10),D(10),None,None,D(14)])
 def test_ma_original_sum_order(self):
  out=self.evals('MA(X,3)',[{'X':D('1e28')},{'X':D(1)},{'X':D(1)},{'X':D(1)}]);self.assertEqual(out[-1],D(1))
 def test_cross_null_and_previous_pair(self):
  out=self.evals('CROSS(X,Y)',[{'X':None,'Y':D(1)},{'X':D(0),'Y':D(1)},{'X':D(2),'Y':D(1)}]);self.assertEqual(out,[None,None,True])
 def test_nonfinite_inputs_rejected(self):
  self.ready()
  with self.assertRaises(ValueError):S.scalar('NaN')
if __name__=='__main__':unittest.main(verbosity=2)
