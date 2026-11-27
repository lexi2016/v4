"""Synthetic, source-bound transition checks kept separate from the Junda regression."""

from datetime import date, timedelta
import unittest

from research.act067b.semantic_shadow import Session
from research.act069a.engine import DamageSpec, EventEngine, Fact, Kind, LaunchSpec, MotherSpec


SOURCE='synthetic-registered-oracle'
DIGEST='a'*64
EPOCH=date(2024,1,2)


def day(index):
    return EPOCH+timedelta(days=2*index)


def bar(index,*,bull=True,volume=100,pct=0,j=10):
    return Session(day(index),10,12,8,11 if bull else 9,volume,pct,10,9,11,j)


class Factory:
    def __init__(self):
        self.i=0

    def make(self,kind,target,observed,*,known=None,truth=True,info=None):
        self.i+=1
        return Fact(f'proof-{self.i}',kind,target,day(observed),day(observed if known is None else known),SOURCE,DIGEST,truth,info)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.f=Factory().make
        self.engine=EventEngine({SOURCE:DIGEST})

    def at(self,index,*facts,**shape):
        return self.engine.advance(bar(index,**shape),facts)

    def mother(self,index,identity='M'):
        return self.f(Kind.MOTHER_ATTACK_BUILDUP,identity,index,info=MotherSpec('support-'+identity,8.5))

    def b1_confirmation(self,index,identity='M'):
        return [self.f(kind,identity,index) for kind in (Kind.B1_PULLBACK,Kind.B1_GENUINE_SUPPORT,Kind.B1_SUPPLY_DIGESTED,Kind.B1_CONFIRM)]

    def launch(self,index,identity='L',base='base'):
        return [self.f(Kind.B2_D0,identity,index,info=LaunchSpec(base)),self.f(Kind.B2_BULLISH_LAUNCH,identity,index),
                self.f(Kind.B2_ACTUAL_DEPARTURE,identity,index)]

    def m25_c(self,index,repair='R',root='M',lost='lost',*,root_reclaimed=True,prior_reclaimed=True,risk=True):
        result=[self.f(Kind.M25_CONFIRM_C,repair,index),self.f(Kind.M25_ORIGINAL_ROOT_RECLAIMED,repair,index,info=root,truth=root_reclaimed),
                self.f(Kind.M25_PRIOR_STRUCTURE_RECLAIMED,repair,index,info=lost,truth=prior_reclaimed)]
        if risk is not None:
            result.append(self.f(Kind.M25_INDEPENDENT_RISK_CLEAR,repair,index,truth=risk))
        return result

    def test_raw_or_bearish_bar_cannot_establish_bullish_mother(self):
        initial=self.at(0,bull=False)
        self.assertEqual(initial['b1_f02_raw'],'TRUE')
        self.assertEqual(initial['b1_mother_event_id'],'')
        actual=self.at(1,self.mother(1),bull=False)
        self.assertEqual(actual['b1_mother_event_id'],'')
        self.assertEqual(actual['b1_formal'],'UNKNOWN')
        self.assertEqual(actual['b2_formal_D0'],'FALSE')

    def test_b1_stable_long_chain_and_sticky_failure_without_resurrection(self):
        self.at(0,self.mother(0))
        for index in range(1,19):
            self.assertEqual(self.at(index)['b1_mother_event_id'],'M')
        eligible=self.at(19,*self.b1_confirmation(19))
        self.assertEqual((eligible['b1_path'],eligible['b1_formal'],eligible['b1_immutable_fail_level']),('FORMAL','TRUE',8.5))
        failure=self.f(Kind.MOTHER_FAILURE,'M',20)
        old=self.at(20,failure)
        self.assertEqual(old['b1_path'],'INVALIDATED')
        tried=self.at(21,*self.b1_confirmation(21))
        self.assertEqual((tried['b1_path'],tried['b1_invalidation_proof_id'],tried['formal_trigger_methods']),('INVALIDATED',failure.fact_id,[]))
        self.at(22,self.mother(22,'NEW'))
        fresh=self.at(23,*self.b1_confirmation(23,'NEW'))
        self.assertEqual((fresh['b1_path'],fresh['b1_mother_event_id']),('FORMAL','NEW'))
        self.assertEqual(eligible['b1_path'],'FORMAL')

    def test_rejected_duplicate_inceptions_leave_engine_unmodified(self):
        self.at(0)
        first=self.f(Kind.MOTHER_ATTACK_BUILDUP,'M',0,known=1,info=MotherSpec('a',8.5))
        second=self.f(Kind.MOTHER_ATTACK_BUILDUP,'M',1,info=MotherSpec('b',8.1))
        with self.assertRaisesRegex(ValueError,'inception identity'):
            self.at(1,first,second)
        self.assertEqual(len(self.engine.bars),1)
        self.assertFalse(self.engine.mothers)
        self.at(1,first)
        self.assertEqual(self.engine.mothers['M'].support_id,'a')

    def test_late_mother_inherits_already_known_failure(self):
        self.at(0)
        failure=self.f(Kind.MOTHER_FAILURE,'M',1)
        self.at(1,failure)
        late=self.f(Kind.MOTHER_ATTACK_BUILDUP,'M',0,known=2,info=MotherSpec('support',8.5))
        observed=self.at(2,late,*self.b1_confirmation(2))
        self.assertEqual((observed['b1_path'],observed['b1_invalidation_proof_id']),('INVALIDATED',failure.fact_id))
        self.assertEqual(observed['formal_trigger_methods'],[])

    def test_unregistered_or_future_and_nonsession_proof_rejected_before_mutation(self):
        future=self.f(Kind.B1_PULLBACK,'M',2)
        with self.assertRaisesRegex(ValueError,'known-at'):
            self.at(0,future)
        forged=Fact('forged',Kind.B1_PULLBACK,'M',day(0),day(0),'bad',DIGEST)
        with self.assertRaisesRegex(ValueError,'authority'):
            self.at(0,forged)
        self.assertFalse(self.engine.bars)

    def test_all_b1_ids_are_evaluated_before_representative_selection(self):
        self.at(0,self.mother(0,'X'),self.mother(0,'Y'),self.mother(0,'WATCH'))
        row=self.at(1,*self.b1_confirmation(1,'X'),*self.b1_confirmation(1,'Y'),self.f(Kind.B1_CONFIRM,'WATCH',1))
        self.assertEqual(row['formal_trigger_methods'],['B1'])
        self.assertEqual([fact['event_id'] for fact in row['formal_trigger_events']],['X','Y'])
        self.assertEqual(row['b1_path'],'FORMAL')

    def test_b2_base_independent_and_late_false_break_blocks_only_future_derivation(self):
        self.at(0,self.f(Kind.B2_BASE_CONFIRMED,'base',0))
        self.at(1,self.f(Kind.B2_SUPPLY_DIGESTED,'base',1))
        first=self.at(2,*self.launch(2))
        self.assertEqual((first['b2_formal_D0'],first['b2_base_event_id'],first['b2_mother_event_id']),('TRUE','base',''))
        self.assertEqual(first['formal_trigger_methods'],['B2_D0'])
        prior=self.at(3,self.f(Kind.B2_RETEST_CONFIRMED,'L',3))
        self.assertEqual(prior['formal_trigger_methods'],['B2_RETEST'])
        late_break=self.f(Kind.B2_NEXT_SESSION_FALSE_BREAK,'L',3,known=4)
        later=self.at(4,late_break,self.f(Kind.B2_RETEST_CONFIRMED,'L',4))
        self.assertEqual((later['b2_path'],later['b2_formal_D0'],later['b2_formal_retest']),('INVALIDATED','TRUE','FALSE'))
        self.assertEqual(later['b2_false_break_known_on'],str(day(4)))
        self.assertEqual((first['b2_path'],prior['b2_formal_retest']),('FORMAL','TRUE'))

    def test_b2_two_retests_and_non_bullish_or_proven_downtrend_block(self):
        self.at(0,self.f(Kind.B2_BASE_CONFIRMED,'base',0),self.f(Kind.B2_SUPPLY_DIGESTED,'base',0))
        row=self.at(1,*self.launch(1,'RED'),bull=False)
        self.assertEqual(row['b2_formal_D0'],'FALSE')
        row=self.at(2,*self.launch(2,'DOWN'),self.f(Kind.B2_DOWNTREND_REBOUND,'DOWN',2))
        self.assertEqual((row['candle_shape_D'],row['b2_formal_D0']),('BULLISH','FALSE'))
        self.at(3,*self.launch(3,'ONE'),*self.launch(3,'TWO'))
        row=self.at(4,self.f(Kind.B2_RETEST_CONFIRMED,'ONE',4),self.f(Kind.B2_RETEST_CONFIRMED,'TWO',4))
        self.assertEqual([e['event_id'] for e in row['formal_trigger_events']],['ONE','TWO'])
        self.assertEqual(row['b2_trend_raw'],'UNKNOWN_PLACEHOLDER')
        self.assertEqual(row['b2_oral_raw'],'UNKNOWN')

    def test_continuation_failure_does_not_relabel_b1_and_is_reconciled_when_late(self):
        self.at(0,self.mother(0))
        first=self.at(1,self.f(Kind.STRONG_CONTINUATION_CONFIRMED,'S',1,info='M'))
        self.assertEqual((first['strong_continuation_path'],first['b1_formal'],first['b3_mapping']),('FORMAL','UNKNOWN','HYPOTHESIS_ONLY'))
        failed=self.at(2,self.f(Kind.STRONG_CONTINUATION_SUPPORT_FAILURE,'S',2),self.f(Kind.STRONG_CONTINUATION_SUPPORT_FAILURE,'LATE',2))
        self.assertEqual((failed['strong_continuation_path'],failed['b1_formal']),('INVALIDATED','UNKNOWN'))
        late=self.at(3,self.f(Kind.STRONG_CONTINUATION_CONFIRMED,'LATE',1,known=3,info='M'))
        self.assertEqual((late['strong_continuation_path'],late['formal_trigger_methods']),('INVALIDATED',[]))

    def test_m25_missing_root_and_unresolved_link_remain_unknown(self):
        self.at(0,self.mother(0))
        self.at(1,self.f(Kind.M25_DAMAGE,'R',1,info=DamageSpec(None,'lost')),
                self.f(Kind.M25_DAMAGE,'OTHER',1,info=DamageSpec('M','lost','missing-earlier')))
        self.at(2,self.f(Kind.M25_TEST,'R',2),self.f(Kind.M25_TEST,'OTHER',2))
        row=self.at(3,*self.m25_c(3),*self.m25_c(3,'OTHER'))
        self.assertEqual((row['m25_path'],row['m25_history_preserved'],row['formal_trigger_methods']),('UNKNOWN','UNKNOWN',[]))
        self.assertIsNone(self.engine.repairs['R'].formal)
        self.assertIsNone(self.engine.repairs['OTHER'].formal)

    def test_m25_multiple_ids_good_not_masked_by_unreclaimed_watch_and_no_drawdown_gate(self):
        self.at(0,self.mother(0))
        for index,names in [(1,('SMALL','LARGE','WATCH')),(2,('SMALL','LARGE','WATCH'))]:
            fn=Kind.M25_DAMAGE if index==1 else Kind.M25_TEST
            self.at(index,*(self.f(fn,ident,index,info=DamageSpec('M','lost') if index==1 else None) for ident in names))
        row=self.at(3,*self.m25_c(3,'SMALL'),*self.m25_c(3,'LARGE'),*self.m25_c(3,'WATCH',prior_reclaimed=False),
                    self.f(Kind.M25_DRAWDOWN_REPORTING,'SMALL',3,info=8.1),self.f(Kind.M25_DRAWDOWN_REPORTING,'LARGE',3,info=37.5))
        self.assertEqual([e['event_id'] for e in row['formal_trigger_events']],['LARGE','SMALL'])
        self.assertEqual(row['m25_path'],'FORMAL')
        self.assertIsNone(self.engine.repairs['WATCH'].formal)
        follow=self.at(4,self.f(Kind.M25_CONFIRM_C,'WATCH',4),self.f(Kind.M25_PRIOR_STRUCTURE_RECLAIMED,'WATCH',4,info='lost',truth=False))
        self.assertEqual((follow['m25_path'],follow['m25_formal']),('WATCH','FALSE'))

    def test_m25_reconciles_known_damage_when_t_late_and_never_resurrects(self):
        self.at(0,self.mother(0))
        self.at(1,self.f(Kind.M25_DAMAGE,'R',1,info=DamageSpec('M','lost')))
        self.at(2)
        damaged=self.f(Kind.M25_NEW_DAMAGE,'R',3)
        early=self.at(3,damaged)
        self.assertNotEqual(early['m25_path'],'INVALIDATED')
        checked=self.at(4,self.f(Kind.M25_TEST,'R',2,known=4))
        self.assertEqual((checked['m25_path'],checked['m25_invalidation_proof_id']),('INVALIDATED',damaged.fact_id))
        late=self.at(5,*self.m25_c(5))
        self.assertEqual((late['m25_path'],late['formal_trigger_methods']),('INVALIDATED',[]))

    def test_m25_fresh_repair_can_reference_same_historical_failed_root(self):
        self.at(0,self.mother(0))
        fail=self.f(Kind.MOTHER_FAILURE,'M',1)
        self.at(1,fail,self.f(Kind.M25_DAMAGE,'R',1,info=DamageSpec('M','lost')))
        self.at(2,self.f(Kind.M25_TEST,'R',2))
        self.at(3,self.f(Kind.M25_DAMAGE,'FRESH',3,info=DamageSpec('M','new-lost','R')))
        self.at(4,self.f(Kind.M25_TEST,'FRESH',4))
        now=self.at(5,*self.m25_c(5,'FRESH',lost='new-lost'))
        self.assertEqual((now['m25_path'],now['m25_original_root_event_id'],now['m25_previous_repair_id']),('FORMAL','M','R'))
        self.assertEqual(now['m25_original_root_invalidation_proof_id'],fail.fact_id)
        self.assertEqual(now['b1_path'],'INVALIDATED')
        old=self.at(6,*self.m25_c(6,'R'))
        self.assertEqual((old['m25_path'],old['formal_trigger_methods']),('INVALIDATED',[]))

    def test_m25_late_completion_requires_new_contemporaneous_c(self):
        self.at(0,self.mother(0))
        self.at(1,self.f(Kind.M25_DAMAGE,'R',1,info=DamageSpec('M','lost')))
        self.at(2,self.f(Kind.M25_TEST,'R',2))
        original=self.at(3,*self.m25_c(3,risk=None))
        self.assertEqual(original['m25_path'],'UNKNOWN')
        late=self.at(4,self.f(Kind.M25_INDEPENDENT_RISK_CLEAR,'R',3,known=4))
        self.assertEqual((late['m25_path'],late['m25_late_completion_status'],late['formal_trigger_methods']),('WATCH','LATE_PROOF_NON_ACTIONABLE',[]))
        current=self.at(5,*self.m25_c(5))
        self.assertEqual((current['m25_path'],current['m25_C_date']),('FORMAL',str(day(5))))
        self.assertEqual(original['m25_formal'],'UNKNOWN')


if __name__=='__main__':
    unittest.main()
