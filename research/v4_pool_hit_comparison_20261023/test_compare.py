"""Targeted boundaries: market keys and content-bound availability gate."""
import unittest
from compare import code,timing,canonical_row,entity_class
class Boundaries(unittest.TestCase):
 def test_market_key_identity(self):
  self.assertEqual(code('SH600000'),'600000.SH')
  self.assertEqual(code('600000.SH'),'600000.SH')
  self.assertEqual(code('SZ.000001'),'000001.SZ')
  self.assertEqual(code('920001.BJ'),'920001.BJ')
  for bad in ['HK.00700','00700','600000.SZ','000001.SH','unknown']:
   self.assertIsNone(code(bad),bad)
 def test_runtime_row_identity(self):
  self.assertEqual(canonical_row({'symbol':'A.600000','code':'600000.SH','market':'A'}),'600000.SH')
  self.assertIsNone(canonical_row({'symbol':'A.600000','code':'000001.SZ','market':'A'}))
  self.assertIsNone(canonical_row({'symbol':'A.600000','market':'HK'}))
  self.assertEqual(canonical_row({'code':'500000','market':'A'}),'500000.A_UNMAPPED')
 def test_content_bound_and_cutoff(self):
  e=dict(complete=True,timing_status='PIT_CONFIRMED',historical_content_bound=True,selection_date='20261016',available_at='2026-10-16T09:25:00+08:00')
  self.assertEqual(timing(e),'PIT_CONFIRMED')
  for change in [dict(historical_content_bound=False),dict(available_at='2026-10-16T09:25:01+08:00'),dict(available_at='2026-10-16T09:00:00')]:
   with self.assertRaises(AssertionError):timing({**e,**change})
  self.assertEqual(timing({**e,'complete':False}),'CANNOT_CONFIRM_INCOMPLETE')
  self.assertEqual(timing({**e,'timing_status':'RETROSPECTIVE'}),'RETROSPECTIVE')
class ETFIdentityOnly(unittest.TestCase):
 def test_frozen_etf_identity_excluded(self):
  plan={('20261016','159915'):{'source_name':'创业板ETF易方达','snapshot_sha256':'fixed'}}
  r={'stock_name':'创业板ETF易方达','_source_artifact_sha256':'fixed'}
  self.assertEqual(entity_class(r,'20261016','159915.A_UNMAPPED',plan),'NON_STOCK_ETF')
  for change in [{'stock_name':'other'},{'_source_artifact_sha256':'drift'}]:
   self.assertEqual(entity_class({**r,**change},'20261016','159915.A_UNMAPPED',plan),'CANNOT_CONFIRM_UNKNOWN_IDENTITY')
 def test_unknown_not_promoted_by_etf_name(self):
  self.assertEqual(entity_class({'stock_name':'Unknown ETF'},'20261016','599999.A_UNMAPPED',{}),'CANNOT_CONFIRM_UNKNOWN_IDENTITY')
 def test_stock_guard_unchanged(self):
  self.assertEqual(entity_class({},'20261016','600000.SH',{}),'STOCK_CODE_RESOLVED')
if __name__=='__main__':unittest.main()
