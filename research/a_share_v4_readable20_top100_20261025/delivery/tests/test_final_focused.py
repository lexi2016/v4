"""Focused identifier-only repair regression tests; no live or financial input reads."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analysis_r3c import identity_from_sources, build_selected_rows


class IdentityJoinR3Tests(unittest.TestCase):
    def test_generic_join_uses_unique_exact_date_authority_and_keeps_conflicts_unknown(self):
        def resolve(raw, keys, conflicts=()):
            return identity_from_sources(raw, None, raw, True, False,
                                         qualified_keys=keys, conflict_keys=conflicts)
        self.assertEqual(resolve('A.600000', ['600000.SH'])[0], '600000.SH')
        self.assertEqual(resolve('A.600000', ['600000.SZ'])[0], '600000.SZ')
        self.assertIsNone(resolve('A.600000', ['600001.SH'])[0])
        self.assertEqual(resolve('A.600000', ['600000.SH', '600000.SZ'])[2],
                         'AMBIGUOUS_QUALIFIED_AUTHORITY_IDENTITY_KEY')
        self.assertEqual(resolve('A.510300', ['510300.SH'], ['510300.SZ'])[2],
                         'SECURITY_TYPE_OR_MARKET_CODE_IDENTITY_CONFLICT')
        self.assertEqual(identity_from_sources('SH.600000', '600000.SH', 'SH.600000', True, True,
                         qualified_keys=['600000.SZ'])[2],
                         'EXPLICIT_VENUE_CONFLICT_WITH_QUALIFIED_AUTHORITY_KEY')

    def test_join_preserves_slots_raw_order_and_unknown_values_and_ignores_label_rank_for_identity(self):
        cell = dict(trade_date='20260928', stage_id='STAGE_0925',
                    A_codes=['A.600000', 'A.510300', 'A.999999'], A_selected_rows=3,
                    A_trio_verified=True, original_saved_binding_run_match=True, A_run_id='frozen-run')
        config = dict(known_identity_conflict_codes=['510300.SZ'], prior_truth_projection='frozen.csv')
        truth = {'600000.SH': {'name': 'current panel display', 'return_pct': -90, 'daily_rank': 999},
                 '510300.SH': {'return_pct': 99, 'daily_rank': 1}}
        rows = build_selected_rows(cell, None, {}, truth, {}, set(), config)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['raw_code'] for r in rows], cell['A_codes'])
        self.assertEqual([r['source_order_index'] for r in rows], [1, 2, 3])
        self.assertEqual([r['hit_state'] for r in rows], ['MISS', 'UNKNOWN', 'UNKNOWN'])
        self.assertEqual(rows[0]['resolved_ts_code'], '600000.SH')
        self.assertIsNone(rows[1]['resolved_ts_code'])
        self.assertIsNone(rows[1]['daily_return_pct'])
        self.assertIn('values_or_ranks_used_for_identity', rows[0]['resolve_provenance'])
        truth['600000.SH']['return_pct'] = 99
        truth['600000.SH']['daily_rank'] = 1
        self.assertEqual(build_selected_rows(cell, None, {}, truth, {'600000.SH': 1}, set(), config)[0]['resolved_ts_code'], rows[0]['resolved_ts_code'])




"""Only the newly evidenced ordinary-vs-backfill FAST_BIND flag branch."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analysis_r3c import accepted_store_link, build_selected_rows

class OrdinaryLinkR3BTests(unittest.TestCase):
    def test_accepted_shared_ordinary_null_is_not_false_and_false_stays_rejected(self):
        cell = dict(trade_date='20261023', stage_id='STAGE_0930_0935', A_codes=['SH.600293'], A_selected_rows=1,
                    A_trio_verified=True, original_saved_binding_run_match=None,
                    A_run_id='frozen-original-run', response_sha256='a' * 64,
                    response_source='REUSED_PINNED_R2_POST140',
                    cell_runtime_identity={'release':'a-share-stage-history-restore-20261025-r2'})
        config = dict(known_identity_conflict_codes=[], prior_truth_projection='frozen.csv')
        truth = {'600293.SH': {'return_pct': 1, 'daily_rank': 200}}
        self.assertTrue(accepted_store_link(cell))
        rows=build_selected_rows(cell,None,{},truth,{},set(),config)
        self.assertEqual(rows[0]['hit_state'],'MISS')
        self.assertEqual(rows[0]['raw_code'],'SH.600293')
        self.assertEqual(rows[0]['resolved_ts_code'],'600293.SH')
        for changes in [{'original_saved_binding_run_match':False}, {'A_trio_verified':False}, {'A_run_id':None}, {'response_source':'UNBOUND'}]:
            candidate={**cell,**changes}
            self.assertFalse(accepted_store_link(candidate))
        self.assertTrue(accepted_store_link({**cell,'original_saved_binding_run_match':True,'response_source':'ROOT_NATIVE_R3_SMOKE_REUSED'}))



"""Regression for the evidenced decimal-text parser tie drift, not benchmark tuning."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analysis_r3c import load_truth

class AcceptedNumericParserR3CTests(unittest.TestCase):
    def test_original_parser_decimal_tie_matches_frozen_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'projection.csv';cache=root/'top.csv';q=root/'q.json'
            ties=[('000504.SZ','10.01','9.1'),('002971.SZ','42.68','38.8'),('003041.SZ','42.02','38.2'),('600343.SH','21.67','19.7'),('600577.SH','8.690000000000001','7.8999999999999995')]
            leading=[(f'{i:06d}.SZ','12','10') for i in range(100001,100096)]
            with p.open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['trade_date','ts_code','close','pre_close'])
                for code,close,pre in [*leading,*ties]: w.writerow(['20260918',code,close,pre])
            with cache.open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['trade_date','ts_code','daily_rank'])
                for rank,(code,_,_) in enumerate([*leading,*ties],1):w.writerow(['20260918',code,rank])
            q.write_text(json.dumps({'excluded_legacy_codes':[]}))
            config={'dates':['20260918'],'prior_truth_projection':str(p),'prior_truth_qualification':str(q),'prior_top100_cache':str(cache)}
            ranks,_,_,parity=load_truth(config,['20260918'])
            self.assertEqual(ranks['20260918']['600577.SH']['pre_close'],7.9)
            self.assertEqual(ranks['20260918']['600577.SH']['daily_rank'],100)
            self.assertTrue(parity['20260918']['strict_rank_parity'])


if __name__=='__main__':
    unittest.main()
