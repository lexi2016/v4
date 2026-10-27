import unittest,importlib.util,json,copy,uuid
from pathlib import Path
from test_bootstrap_step import E,ALL,binding
H=Path(__file__).resolve().parent
class TestJournal(unittest.TestCase):
 def module(self):
  p=H/'journal.py';self.assertTrue(p.exists(),'paired journal absent');s=importlib.util.spec_from_file_location('paired_journal_test',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def example(self):
  rows=ALL[:10];b=binding(rows);st=E.bootstrap('002608.SZ',rows,rows[-1]['trade_date'],b);row,new=E.step(st,ALL[10]['ohlcv'],b);return row,new
 def test_pair_commit_read_and_idempotent(self):
  m=self.module();j=m.Journal('test_'+uuid.uuid4().hex);row,st=self.example();r=j.commit('002608.SZ',row,st);self.assertEqual(r['status'],'PAIR_CANDIDATE_WRITTEN');self.assertEqual(j.read('002608.SZ',row['trade_date'])['daily'],row);self.assertEqual(j.commit('002608.SZ',row,st)['status'],'PAIR_IDENTICAL_REPLAY')
 def test_incomplete_day_not_exposed(self):
  m=self.module();j=m.Journal('test_'+uuid.uuid4().hex);row,st=self.example();p=j.day_path('002608.SZ',row['trade_date']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(E.canonical(row))
  with self.assertRaisesRegex(ValueError,'INCOMPLETE'):j.read('002608.SZ',row['trade_date'])
  with self.assertRaisesRegex(ValueError,'ORPHAN'):j.commit('002608.SZ',row,st)
 def test_bad_state_hash_and_day_mismatch(self):
  m=self.module();j=m.Journal('test_'+uuid.uuid4().hex);row,st=self.example();bad=copy.deepcopy(st);bad['last_date']=20261027
  with self.assertRaises(ValueError):j.commit('002608.SZ',row,bad)
 def test_no_arbitrary_path(self):
  m=self.module()
  with self.assertRaises(ValueError):m.Journal('../outside')
if __name__=='__main__':unittest.main(verbosity=2)
