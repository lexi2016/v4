import importlib.util
import unittest
from pathlib import Path

class EntryTests(unittest.TestCase):
 def entry(self):
  path=Path(__file__).with_name('entry.py')
  self.assertTrue(path.exists(), 'daily date-safe entry missing')
  spec=importlib.util.spec_from_file_location('daily_entry',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_beijing_date(self):
  m=self.entry();self.assertEqual(m.beijing_date('2026-10-23T16:01:00+00:00'),'20261024')
 def test_stale_config(self):
  m=self.entry()
  with self.assertRaisesRegex(ValueError,'STALE_CONFIG'):m.require_date({'date':'20261023'},'20261026')
 def test_current_config(self):
  m=self.entry();self.assertIsNone(m.require_date({'date':'20261026','vintage':'20261026','g4_trade_date':'20261026','events_vintage':'20261026'},'20261026'))
 def test_partial_dates(self):
  m=self.entry()
  with self.assertRaisesRegex(ValueError,'STALE_CONFIG'):m.require_date({'date':'20261026'},'20261026')
 def test_blocked_is_nonzero(self):
  m=self.entry();self.assertEqual(m.exit_status({'status':'BLOCKED_PUBLICATION','counts':{'failed':0}}),2)
 def test_weekend_without_daily_inputs(self):
  import subprocess, json, sys
  run=subprocess.run([sys.executable,str(Path(__file__).with_name('entry.py')),'--date','20261024'],capture_output=True,text=True)
  self.assertEqual(run.returncode,0,run.stdout)
  self.assertEqual(json.loads(run.stdout)['status'],'MARKET_CLOSED_NO_UPDATE')
if __name__=='__main__':unittest.main()
