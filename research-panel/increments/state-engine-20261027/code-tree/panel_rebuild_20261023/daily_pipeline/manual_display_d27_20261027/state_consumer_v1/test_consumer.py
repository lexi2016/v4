import unittest,importlib.util,json,copy
from pathlib import Path
H=Path(__file__).resolve().parent
class TestConsumer(unittest.TestCase):
 def mod(self):
  p=H/'consumer.py';self.assertTrue(p.exists(),'consumer absent');s=importlib.util.spec_from_file_location('consumer_test',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_scope_routes_exact(self):
  m=self.mod();a=m.authority();self.assertEqual(set(a['routes']),{'002608.SZ','000001.SZ','300053.SZ'});self.assertEqual(a['routes']['300053.SZ'],'missing_step')
 def test_outside_symbol_rejected_before_context(self):
  m=self.mod()
  with self.assertRaises(ValueError):m.route('600000.SH')
 def test_public_reader_closed(self):
  m=self.mod();self.assertFalse(m.query('000001.SZ',20261027)['research_consumption_allowed'])
 def test_fixed_paths_only(self):
  m=self.mod()
  for sym in ('../002608.SZ','002608.SZ/../../x','000001.SH'):
   with self.assertRaises(ValueError):m.route(sym)
 def test_calendar_source_scope_purpose(self):
  m=self.mod();a=m.authority();self.assertFalse(a['display_allowed']);self.assertFalse(a['production_allowed']);self.assertEqual(a['date'],20261027)
if __name__=='__main__':unittest.main(verbosity=2)

class TestCandidateResume(unittest.TestCase):
 def mod(self):
  s=importlib.util.spec_from_file_location('consumer_resume_test',H/'consumer.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_frozen_completed_index_loads_without_compute(self):
  m=self.mod();self.assertTrue(hasattr(m,'load_completed_index'),'resume index gate absent');idx=m.load_completed_index('canary3_20261027T115802Z');self.assertEqual(set(idx['entries']),set(m.authority()['symbols']))
 def test_other_or_path_run_rejected(self):
  m=self.mod();self.assertTrue(hasattr(m,'load_completed_index'),'resume index gate absent')
  for name in ('../x','arbitrary_run'):
   with self.assertRaises(ValueError):m.load_completed_index(name)

class TestReviewedReuse(unittest.TestCase):
 def test_actual1556_check_binds_exact_tail(self):
  s=importlib.util.spec_from_file_location('reviewed_reuse_test',H/'consumer.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);self.assertTrue(hasattr(m,'reviewed_reuse'),'review gate absent')
  self.assertEqual(m.reviewed_reuse('000001.SZ')['tail_sha256'],'d070a4815797aaf6a31beb083dcd1a861fe73513f756a0ea8f713383d7091231')
  with self.assertRaises(ValueError):m.reviewed_reuse('300053.SZ')
