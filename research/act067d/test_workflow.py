"""Targeted regression tests for the frozen ACT-067D user contract."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from research.act067b.semantic_shadow import Session, sha256
from research.act067d.engine import Shadow
from research.act067d.plot import geometry, render
from research.act067d.workflow import CONTRACT_SHA, CSV, ZIP, chart_package, load_rules, read_csv


EPOCH=date(2024,1,1)


def day(i, *, o=100,h=101,l=99,c=100,v=100,p=0,w=99.5,y=99,bbi=101,j=45):
    return Session(EPOCH+timedelta(days=2*i),o,h,l,c,v,p,w,y,bbi,j)


class ShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['ACT067D_TEST_ROOT'])
        cls.rules=load_rules(cls.root/'output')

    def warm(self):
        engine=Shadow(self.rules)
        for index in range(40):
            engine.advance(day(index))
        return engine

    def test_19_never_promotes_same_day_raw_and_keeps_certification_distinct(self):
        s=self.warm()
        raw=s.advance(day(40,h=106,l=99,c=102,p=2,j=10))
        self.assertEqual((raw['b1_raw'],raw['b1_phase'],raw['b1_formal_shadow']),('TRUE','RAW_ONLY','FALSE'))
        nested=s.advance(day(41,h=102,l=99,c=99.8,p=-2,j=18,v=60))
        self.assertEqual(nested['b1_formal_shadow'],'TRUE')
        self.assertEqual(nested['b1_formal_certified'],'UNKNOWN')
        self.assertEqual(nested['b1_anchor_age_td'],1)
        self.assertEqual(nested['b1_pullback_td'],1)
        self.assertEqual(nested['b1_trough_vol_ma5_ratio'],0.6)
        self.assertEqual(nested['b1_trough_vol_ma10_ratio'],0.6)
        self.assertEqual(nested['b1_attack_peak_ratio'],0.6)
        self.assertEqual(nested['b1_W_intraday'],'PIERCE_RECOVER')
        self.assertEqual(nested['risk_clear_shadow'],'TRUE')
        self.assertEqual(nested['risk_clear_certified'],'UNKNOWN')

    def test_20_tracks_keep_strict_thresholds_separate_and_retest_requires_earlier_d0(self):
        s=self.warm()
        first=s.advance(day(40,c=100.5,l=98.5,p=4,v=120,j=13))
        self.assertEqual([first[f'{track}_raw'] for track in self.rules['method_20']['tracks']],
                         ['FALSE','TRUE','FALSE','FALSE','UNKNOWN'])
        self.assertEqual(first['B2_1006_SCREEN_retest_anchor'],'')
        next_day=s.advance(day(41,c=100.3,l=98.7,p=4.01,v=142,j=12))
        self.assertEqual(next_day['USER_FORMULA_B2_F03_raw'],'TRUE')
        self.assertEqual(next_day['B2_151_PREV_VOL_X1_20_raw'],'FALSE')
        self.assertEqual(next_day['B2_1006_SCREEN_retest_anchor'],str(day(40).day))
        self.assertEqual(next_day['b2_oral_vol_vs_prev'],142/120)
        self.assertEqual(next_day['b2_f03_prior4_denominator'],105)
        risk=s.advance(day(42,o=100,h=101,l=92,c=94,p=-6,v=190,j=22))
        self.assertEqual(risk['risk_clear_shadow'],'FALSE')
        self.assertEqual(risk['B2_TREND_CONFIRMATION_formal_retest_shadow'],'UNKNOWN')

    def make_chain(self, peak, finish):
        s=self.warm()
        s.advance(day(40,o=102,h=peak,l=100,c=106,v=170,p=6,w=103,y=102))
        s.advance(day(41,o=102,h=105,l=101,c=103,w=101,y=99))
        s.advance(day(42,o=101,h=104,l=100,c=103,w=101,y=99))
        damaged=s.advance(day(43,o=99,h=100,l=97,c=98,w=100,y=98,p=-2))
        tested=s.advance(day(44,o=98,h=99.5,l=97.8,c=98.4,w=100,y=98,v=60,p=.4))
        checked=s.advance(day(45,o=96,h=finish+.1,l=95.9,c=finish,w=99,y=97,v=170,p=3.3))
        old=s.advance(day(46,o=98,h=100,l=97,c=98,w=100,y=98,v=100,p=-1))
        return damaged,tested,checked,old,s.damage_history

    def test_old_root_blocks_current_rebuild_and_breach_persists(self):
        damaged,tested,checked,old,history=self.make_chain(108,99.8)
        self.assertEqual(damaged['m25_phase'],'D_DAMAGE')
        self.assertEqual(tested['m25_phase'],'T_YELLOW_TEST')
        self.assertEqual(checked['m25_phase'],'C_REBUILD_CONFIRM')
        self.assertEqual(checked['risk_clear_shadow'],'TRUE')
        self.assertEqual(checked['m25_original_root_clear_now'],'FALSE')
        self.assertEqual(checked['m25_rebuild_shadow'],'FALSE')
        self.assertEqual(old['m25_previous_terminal_record']['original_root_clear'],'FALSE')
        self.assertEqual(old['m25_previous_terminal_record']['market_risk_clear'],'TRUE')
        self.assertEqual(old['m25_previous_terminal_record']['historical_breach'],'TRUE')
        self.assertEqual([event['status'] for event in history[:3]],['ACTIVATED','T_YELLOW_TEST','C_REBUILD_CONFIRM'])

    def test_25_rebuilt_above_root_preserves_prior_break_and_no_drawdown_gate(self):
        cases=[self.make_chain(high,101)[2] for high in (108,140)]
        self.assertLess(cases[0]['m25_damage_drawdown_pct_reporting_only'],15)
        self.assertGreater(cases[1]['m25_damage_drawdown_pct_reporting_only'],20)
        for row in cases:
            self.assertEqual(row['m25_old_floor_ever_broken_through_test'],'TRUE')
            self.assertEqual(row['m25_original_root_clear_now'],'TRUE')
            self.assertEqual(row['m25_rebuild_shadow'],'TRUE')
            self.assertEqual(row['m25_rebuild_certified'],'UNKNOWN')

    def test_actual_25_intercepts_are_bound_to_distinct_risk_components(self):
        rows={row['date']:row for row in read_csv(self.root/'output'/CSV)}
        origin,market=rows['2022-01-24'],rows['2025-01-24']
        self.assertEqual(origin['m25_c_rebuild_price_today'], 'TRUE')
        self.assertEqual((origin['m25_original_root_clear_now'],origin['risk_clear_shadow'],origin['m25_rebuild_shadow']),('FALSE','TRUE','FALSE'))
        self.assertEqual((market['m25_c_rebuild_price_today'],market['risk_clear_shadow'],market['m25_rebuild_shadow']),('TRUE','FALSE','FALSE'))
        self.assertTrue(origin['blind_chart_id'] and market['blind_chart_id'])

    def test_future_append_preserves_exact_anonymized_blind_zip_and_marks_offscale(self):
        bars=[day(i) for i in range(35)]
        rules=self.rules['charts']
        bounds=geometry(bars,rules)
        future=[day(i) for i in range(35,50)]
        changed=[*future[:-1],replace(future[-1],high=100000,volume=10**9)]
        stable_bounds=dict(bounds)
        _,normal=render(future,bounds,rules,forward=True)
        _,clip=render(changed,bounds,rules,forward=True)
        self.assertEqual(clip,dict(price=1,volume=1,j=0))
        self.assertEqual(normal,dict(price=0,volume=0,j=0))
        self.assertEqual(bounds,stable_bounds)
        with TemporaryDirectory(dir=self.root/'evidence') as folder:
            root=Path(folder)
            path=root/'sessions.csv'
            fields=('date','open','high','low','close','volume','pct_change','W','Y','BBI','J')
            with path.open('w',newline='') as stream:
                writer=csv.writer(stream)
                writer.writerow(fields)
                writer.writerows((b.day,b.open,b.high,b.low,b.close,b.volume,b.pct,b.w,b.y,b.bbi,b.j) for b in bars)
            longer=root/'later.csv'
            longer.write_bytes(path.read_bytes()+b'INVALID_AFTER_EXACT_D\n')
            selected=[{'chart_id':'A01','date':str(bars[-1].day),'td_idx':34}]
            first,second=root/'a.zip',root/'b.zip'
            chart_package(first,path,selected,rules)
            chart_package(second,longer,selected,rules)
            self.assertEqual(sha256(first),sha256(second))
            with ZipFile(first) as archive:
                item=json.loads(archive.read('MANIFEST_SHA256.json'))['charts'][0]
                self.assertEqual((item['D'],item['max_date_used'],item['ylim_source']),(selected[0]['date'],selected[0]['date'],'D_ONLY_SLICE'))
                self.assertEqual(hashlib.sha256(archive.read(item['file'])).hexdigest(),item['sha256'])

    def test_frozen_actual_domains_and_prefix_count(self):
        receipt=json.loads((self.root/'evidence'/'shadow_receipt.json').read_bytes())
        self.assertEqual(receipt['contract_sha256'],CONTRACT_SHA)
        self.assertEqual(receipt['unregistered_status_rows'],0)
        self.assertEqual(len(receipt['common_prefix_equality_dates']),3)
        self.assertEqual(receipt['status_fields_validated'],85)
        with ZipFile(self.root/'output'/ZIP) as archive:
            cases=json.loads(archive.read('MANIFEST_SHA256.json'))['charts']
            self.assertEqual(len(cases),12)
            for case in cases:
                self.assertLessEqual(case['max_date_used'],case['D'])
                bars=json.loads(archive.read(case['window_file']))['rows']
                self.assertEqual([b['td'] for b in bars],list(range(-34,1)))


if __name__=='__main__':
    unittest.main()
