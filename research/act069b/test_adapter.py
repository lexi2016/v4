"""Source-bound synthetic controls for the ACT-069B historical adapter."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import os
import unittest

from research.act069b.adapter import Adapter, Bar, Envelope, Kind, Mark, Segment, Source, Support, Terminal, through_bars
from research.act069b.workflow import CONTRACT_SHA, DAY, LEDGER, csv_bytes, load_contract, validate


DAYS=tuple(date.fromisoformat(text) for text in ('2024-01-05','2024-01-08','2024-01-09','2024-01-10','2024-01-11','2024-01-12'))
WEEKEND=date(2024,1,6)
MARK_SHA='a'*64
TERMINAL_SHA='b'*64
PRICE_BASIS='QFQ_ASOF'


def bar(i,*,op=11,high=13,low=9,close=11,volume=100):
    return Bar(DAYS[i],op,high,low,close,volume)


def fact(ident,occurred,first=None,terminal=False):
    return Envelope(ident,'terminal' if terminal else 'objects',TERMINAL_SHA if terminal else MARK_SHA,occurred,first or occurred)


def support(ident='S',occurred=DAYS[0],first=None,lo=10,hi=12):
    return Support(fact(ident,occurred,first),lo,hi,PRICE_BASIS)


def by_fact(rows):
    return {(row['primitive_id'],row['fact_name']):row for row in rows}


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['ACT069B_TEST_ROOT'])
        cls.contract=load_contract(cls.root/'evidence')

    def setUp(self):
        self.adapter=Adapter(self.contract,{
            'objects':Source('fixture:objects',MARK_SHA,frozenset({Kind.KEY_K,Kind.TURNING_POINT,Kind.SUPPORT,Kind.SEGMENT})),
            'terminal':Source('fixture:act069a-terminal',TERMINAL_SHA,frozenset({Kind.ACT069A_TERMINAL})),
        })

    def test_known_at_weekend_preserves_both_marks_with_independent_prices(self):
        self.adapter.advance(bar(0))
        initial=by_fact(self.adapter.snapshot())
        self.assertEqual(initial['P1','registered_key_k']['fact_value'],'UNKNOWN')
        mark1=Mark(fact('K1',DAYS[0],WEEKEND),Kind.KEY_K,12.5,PRICE_BASIS)
        mark2=Mark(fact('K2',DAYS[1]),Kind.KEY_K,10.2,PRICE_BASIS)
        pivot=Mark(fact('V1',DAYS[0],WEEKEND),Kind.TURNING_POINT,9.8,PRICE_BASIS)
        self.adapter.advance(bar(1),[mark1,mark2,pivot])
        snapshot=by_fact(self.adapter.snapshot())
        marks=json.loads(snapshot['P1','registered_key_k']['fact_value'])
        self.assertEqual([(m['object_id'],m['price'],m['first_knowable']) for m in marks], [('K1',12.5,str(WEEKEND)),('K2',10.2,str(DAYS[1]))])
        self.assertTrue(all(MARK_SHA in m['source_locator'] for m in marks))
        self.assertEqual(snapshot['P1','registered_turning_point']['first_knowable_date'],str(WEEKEND))
        self.assertEqual(initial['P1','registered_key_k']['fact_value'],'UNKNOWN')

    def test_ordinary_bullish_volume_and_p5_cannot_fill_authority(self):
        self.adapter.advance(bar(0,op=9,close=12,volume=600))
        rows=by_fact(self.adapter.snapshot())
        self.assertEqual(rows['P1','candle_direction']['fact_value'],'BULLISH')
        self.assertEqual(rows['P2','registered_support_object']['fact_value'],'UNKNOWN')
        self.assertEqual(rows['P4','registered_segment']['fact_value'],'UNKNOWN')
        self.assertEqual(rows['P5','stock_session_bar_observed']['handoff_status'],'OBSERVED_D_ONLY')
        for name in ('official_historical_st_status','official_historical_suspension_status','effective_external_risk_evidence','source_bound_structural_veto'):
            self.assertEqual(rows['P5',name]['fact_value'],'UNKNOWN')
        self.assertEqual(rows['P5','historical_point_in_time_status']['fact_value'],'CANNOT_CONFIRM')

    def test_band_contact_and_pierce_are_distinct_from_consecutive_relations(self):
        self.adapter.advance(bar(0,op=11,close=11),[support()])
        base=by_fact(self.adapter.snapshot(anchor_id='S'))
        self.assertEqual(base['P2','range_overlaps_registered_support']['fact_value'],'TRUE')
        self.assertEqual(base['P2','close_reclaims_intraday_pierce']['fact_value'],'TRUE')
        self.assertEqual(base['P2','close_vs_registered_support_band']['fact_value'],'WITHIN')
        self.assertEqual(base['P3','reclaim']['gap_reason'],'SUPPORT_PREDECESSOR_STATE_UNBOUND')
        self.adapter.advance(bar(1,op=11,close=9.5,volume=160))
        lost=by_fact(self.adapter.snapshot(anchor_id='S'))
        self.assertEqual(lost['P3','close_loss']['fact_value'],'TRUE')
        self.assertEqual(lost['P3','relose']['fact_value'],'FALSE')
        self.assertIn('stock_session_index=0..1;anchor_visible_prefix',lost['P3','relose']['source_locator'])
        self.assertEqual(json.loads(lost['P2','support_session_price_and_volume_change']['fact_value'])['volume_vs_prior_ratio'],1.6)
        self.assertEqual(float(lost['P2','close_distance_to_registered_support_price']['fact_value']),-.5)
        self.adapter.advance(bar(2,op=10,close=12))
        regained=by_fact(self.adapter.snapshot(anchor_id='S'))
        self.assertEqual(regained['P3','reclaim']['fact_value'],'TRUE')
        self.adapter.advance(bar(3,op=10,close=9))
        again=by_fact(self.adapter.snapshot(anchor_id='S'))
        self.assertEqual(again['P3','relose']['fact_value'],'TRUE')
        self.assertIn('stock_session_index=0..3;anchor_visible_prefix',again['P3','relose']['source_locator'])
        self.assertEqual(again['P3','anchored_invalidation']['fact_value'],'UNKNOWN')
        self.assertEqual(again['P5','source_bound_structural_veto']['fact_value'],'UNKNOWN')

    def test_degenerate_level_and_previous_only_provenance(self):
        self.adapter.advance(bar(0,volume=0),[support(lo=10,hi=10)])
        self.adapter.advance(bar(1,op=9,close=12,volume=115))
        result=by_fact(self.adapter.snapshot(anchor_id='S'))
        self.assertEqual(result['P2','close_vs_registered_support_band']['fact_value'],'ABOVE')
        self.assertEqual(float(result['P2','close_distance_to_registered_support_price']['fact_value']),2)
        self.assertEqual(result['P3','intraday_down_pierce_from_open']['fact_value'],'FALSE')
        self.assertEqual(result['P2','close_reclaims_intraday_pierce']['fact_value'],'TRUE')
        self.assertIn('stock_session_index=0;date=2024-01-05',result['P1','prior_session_ohlcv_ref']['source_locator'])
        self.assertNotIn(str(DAYS[1]),result['P1','prior_session_ohlcv_ref']['source_locator'])
        self.assertIn('stock_session_index=0..1',result['P1','volume_vs_prior_session_ratio']['source_locator'])
        self.assertEqual(result['P1','volume_vs_prior_session_ratio']['gap_reason'],'ZERO_COMPARISON_DENOMINATOR')

    def test_unique_exact_anchored_terminal_is_the_only_structural_veto_source(self):
        self.adapter.advance(bar(0),[support()])
        forged=Terminal(fact('forged',DAYS[1]),'S','B1-1')
        with self.assertRaisesRegex(ValueError,'authorized source'):
            self.adapter.advance(bar(1),[forged])
        self.assertEqual(len(self.adapter.bars),1)
        terminal=Terminal(fact('terminal-S',DAYS[0],WEEKEND,terminal=True),'S','B1-1')
        self.adapter.advance(bar(1),[terminal])
        current=by_fact(self.adapter.snapshot(anchor_id='S'))
        loss=current['P3','anchored_invalidation']
        veto=current['P5','source_bound_structural_veto']
        value=json.loads(loss['fact_value'])
        self.assertEqual((value['state'],value['anchor_id'],value['event_chain_id']),('INVALIDATED','S','B1-1'))
        self.assertEqual(loss['first_knowable_date'],str(WEEKEND))
        self.assertEqual({k:v for k,v in loss.items() if k not in ('primitive_id','fact_name')},
                         {k:v for k,v in veto.items() if k not in ('primitive_id','fact_name')})
        self.assertEqual(current['P5','effective_external_risk_evidence']['fact_value'],'UNKNOWN')
        self.assertEqual(by_fact(self.adapter.snapshot(anchor_id='other'))['P5','source_bound_structural_veto']['fact_value'],'UNKNOWN')

    def test_segment_witness_uses_exact_registered_endpoints_and_no_lookahead(self):
        self.adapter.advance(bar(0,close=9.5))
        self.adapter.advance(bar(1,op=9,close=12,volume=180))
        self.adapter.advance(bar(2,op=12,close=10,volume=120))
        self.assertEqual(by_fact(self.adapter.snapshot(segment_id='SEG'))['P4','registered_segment']['fact_value'],'UNKNOWN')
        event=Segment(fact('SEG',DAYS[2],DAYS[3]),DAYS[1],DAYS[2])
        self.adapter.advance(bar(3,op=9,close=12,volume=999),[event])
        current=by_fact(self.adapter.snapshot(segment_id='SEG'))
        seq=current['P4','chronological_candle_volume']
        bars=json.loads(seq['fact_value'])
        self.assertEqual([item['date'] for item in bars],[str(DAYS[1]),str(DAYS[2])])
        self.assertIsNone(bars[0]['prior_close'])
        self.assertIsNone(bars[0]['close_minus_prior_close'])
        self.assertEqual(bars[1]['prior_close'],12)
        self.assertEqual(bars[1]['close_minus_prior_close'],-2)
        self.assertIn('stock_session_index=1..2;segment=1..2',seq['source_locator'])
        self.assertEqual((float(current['P4','up_candle_volume']['fact_value']),float(current['P4','down_candle_volume']['fact_value'])),(180,120))
        self.assertEqual(seq['first_knowable_date'],str(DAYS[3]))

    def test_temporal_source_and_price_basis_checks_fail_before_mutation(self):
        self.adapter.advance(bar(0))
        scenarios=(
            support(occurred=DAYS[2]),
            Support(fact('I',DAYS[1],DAYS[0]),10,12,PRICE_BASIS),
            support(occurred=DAYS[0]),
            Support(fact('BAD-BASIS',DAYS[1]),10,12,'WRONG'),
            support(occurred=DAYS[1],lo=11,hi=10),
            Segment(fact('FWD',DAYS[1]),DAYS[0],DAYS[2]),
        )
        for item in scenarios:
            with self.assertRaises(ValueError):
                self.adapter.advance(bar(1),[item])
        self.assertEqual(len(self.adapter.bars),1)
        self.assertEqual(self.adapter.object_ids,set())

    def test_poisoned_next_bar_does_not_change_exact_D_prefix_csv(self):
        with TemporaryDirectory(dir=self.root/'evidence') as tmp:
            folder=Path(tmp)
            p=folder/'prefix.csv'; q=folder/'has_future.csv'
            with p.open('w',newline='') as handle:
                writer=csv.writer(handle); writer.writerow(('date','open','high','low','close','volume'))
                writer.writerows((b.day,b.open,b.high,b.low,b.close,b.volume) for b in (bar(0),bar(1)))
            q.write_bytes(p.read_bytes()+b'POISON_POST_D\n')
            outputs=[]
            for src in (p,q):
                engine=Adapter(self.contract,self.adapter.sources)
                result=[]
                for item in through_bars(src,DAYS[1]):
                    engine.advance(item,[support(occurred=DAYS[0],first=WEEKEND)] if item.day==DAYS[1] else [])
                    result.extend(engine.snapshot(anchor_id='S'))
                outputs.append(csv_bytes(result,self.contract['ledger_fields']))
            self.assertEqual(*outputs)

    def test_actual_bytes_fit_contract_and_roundtrip(self):
        def read(name):
            with (self.root/'output'/name).open(encoding='utf-8-sig',newline='') as stream:
                return list(csv.DictReader(stream))
        facts,days=read(LEDGER),read(DAY)
        self.assertEqual(len(facts),12040)
        self.assertEqual(len(days),344)
        validate(facts,days,self.contract)
        receipt=json.loads((self.root/'evidence'/'adapter_receipt.json').read_bytes())
        self.assertEqual(receipt['freeze_sha256'],CONTRACT_SHA)
        self.assertEqual(len(receipt['prefixes']),3)
        self.assertEqual(receipt['handoff_status_counts'],{'OBSERVED_D_ONLY':2752,'MISSING_SOURCE':9288})


if __name__=='__main__':
    unittest.main()
