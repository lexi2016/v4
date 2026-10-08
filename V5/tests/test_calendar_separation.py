"""Frozen calendar tests; no new business calendar is invented here."""
import hashlib, importlib.util, json, sys, unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE/'vendor'/'rebound_baseline'

class CalendarSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ROOT/'contracts'/'trading_calendar.py'
        descriptor=json.loads((BASE/'contracts'/'rebound_source_manifest.json').read_text())
        entry=next(e for e in descriptor['entries'] if e['relative_path']=='contracts/trading_calendar.py')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('SOURCE_SHA_MISMATCH')
        spec=importlib.util.spec_from_file_location('frozen_calendar_test_only',path)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        cls.module=module;cls.calendar=module.load_market_calendar()
    def test_hk_open_does_not_follow_a_closed(self):
        states=self.module.resolve_market_states(self.calendar,'20261007')
        self.assertEqual(states['a_share'].value,'NON_TRADING_DAY')
        self.assertEqual(states['hk_securities'].value,'FULL_TRADING_DAY')
        self.assertEqual(states['hk_connect'].value,'NON_TRADING_DAY')
    def test_reopening_is_independent(self):
        states=self.module.resolve_market_states(self.calendar,'20261008')
        self.assertEqual(states['a_share'].value,'FULL_TRADING_DAY')
        self.assertEqual(states['hk_securities'].value,'FULL_TRADING_DAY')
        self.assertEqual(states['hk_connect'].value,'FULL_TRADING_DAY')
    def test_outside_frozen_year_not_assumed_open(self):
        try:states=self.module.resolve_market_states(self.calendar,'20270104')
        except ValueError:return
        self.assertTrue(all(s.value=='UNKNOWN' for s in states.values()))
if __name__=='__main__':unittest.main()
