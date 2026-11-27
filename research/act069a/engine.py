"""Typed, known-at structural state machine for the isolated ACT-069A study."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite
import re

from research.act067b.semantic_shadow import Session, conjunction, disjunction, status


class Kind(str, Enum):
    MOTHER_ATTACK_BUILDUP = 'MOTHER_ATTACK_BUILDUP'
    MOTHER_FAILURE = 'MOTHER_FAILURE'
    B1_PULLBACK = 'B1_PULLBACK'
    B1_GENUINE_SUPPORT = 'B1_GENUINE_SUPPORT'
    B1_SUPPLY_DIGESTED = 'B1_SUPPLY_DIGESTED'
    B1_CONFIRM = 'B1_CONFIRM'
    B2_BASE_CONFIRMED = 'B2_BASE_CONFIRMED'
    B2_SUPPLY_DIGESTED = 'B2_SUPPLY_DIGESTED'
    B2_D0 = 'B2_D0'
    B2_BULLISH_LAUNCH = 'B2_BULLISH_LAUNCH'
    B2_ACTUAL_DEPARTURE = 'B2_ACTUAL_DEPARTURE'
    B2_DOWNTREND_REBOUND = 'B2_DOWNTREND_REBOUND'
    B2_NEXT_SESSION_FALSE_BREAK = 'B2_NEXT_SESSION_FALSE_BREAK'
    B2_RETEST_CONFIRMED = 'B2_RETEST_CONFIRMED'
    STRONG_CONTINUATION_CONFIRMED = 'STRONG_CONTINUATION_CONFIRMED'
    STRONG_CONTINUATION_SUPPORT_FAILURE = 'STRONG_CONTINUATION_SUPPORT_FAILURE'
    M25_DAMAGE = 'M25_DAMAGE'
    M25_TEST = 'M25_TEST'
    M25_CONFIRM_C = 'M25_CONFIRM_C'
    M25_ORIGINAL_ROOT_RECLAIMED = 'M25_ORIGINAL_ROOT_RECLAIMED'
    M25_PRIOR_STRUCTURE_RECLAIMED = 'M25_PRIOR_STRUCTURE_RECLAIMED'
    M25_INDEPENDENT_RISK_CLEAR = 'M25_INDEPENDENT_RISK_CLEAR'
    M25_NEW_DAMAGE = 'M25_NEW_DAMAGE'
    M25_DRAWDOWN_REPORTING = 'M25_DRAWDOWN_REPORTING'


BIRTH_KINDS = (Kind.MOTHER_ATTACK_BUILDUP, Kind.B2_D0, Kind.STRONG_CONTINUATION_CONFIRMED, Kind.M25_DAMAGE)

class Path(str, Enum):
    FORMAL = 'FORMAL'
    WATCH = 'WATCH'
    UNKNOWN = 'UNKNOWN'
    INVALIDATED = 'INVALIDATED'


class Shape(str, Enum):
    BULLISH = 'BULLISH'
    BEARISH = 'BEARISH'
    FLAT = 'FLAT'


@dataclass(frozen=True)
class MotherSpec:
    support_id: str
    failure_level: float


@dataclass(frozen=True)
class LaunchSpec:
    base_id: str
    mother_id: str | None = None


@dataclass(frozen=True)
class DamageSpec:
    root_id: str | None
    lost_structure_id: str
    previous_repair_id: str | None = None


@dataclass(frozen=True)
class Fact:
    fact_id: str
    kind: Kind
    target_id: str
    observed_on: date
    known_on: date
    source_id: str
    source_sha256: str
    truth: bool = True
    info: MotherSpec | LaunchSpec | DamageSpec | str | float | None = None

    def reference(self):
        return {'fact_id': self.fact_id, 'kind': self.kind.value, 'known_on': self.known_on.isoformat(),
                'observed_on': self.observed_on.isoformat(), 'source_id': self.source_id,
                'source_sha256': self.source_sha256, 'target_id': self.target_id}


@dataclass(frozen=True)
class Mother:
    identity: str
    origin: Fact
    support_id: str
    failure_level: float


@dataclass(frozen=True)
class Launch:
    identity: str
    origin: Fact
    base_id: str
    mother_id: str | None
    original_formal: bool | None


@dataclass(frozen=True)
class RepairIdentity:
    identity: str
    damage: Fact
    root: Mother | None
    lost_structure_id: str
    previous_repair_id: str | None


@dataclass
class Repair:
    data: RepairIdentity
    test: Fact | None = None
    candidate: Fact | None = None
    invalidated: Fact | None = None
    formal: Fact | None = None


def check(predicate, *values):
    return None if None in values else predicate(*values)


def fact_day(item):
    return item.observed_on.isoformat() if item else ''


def evidence_path(result):
    return Path.FORMAL if result is True else Path.WATCH if result is False else Path.UNKNOWN


def identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_.:@/-]+', value))


def emit(events,method,proof,day):
    events.append({'method':method,'event_id':proof.target_id,'proof_id':proof.fact_id,
                   'observed_on':proof.observed_on.isoformat(),'decision_on':day.isoformat()})


class EventEngine:
    """Input bars convey literal observation only. Structural transitions require registered facts."""

    def __init__(self, source_registry):
        if any(not identifier(name) or not re.fullmatch(r'[0-9a-f]{64}', digest)
               for name, digest in source_registry.items()):
            raise ValueError('Evidence registry must bind source IDs to exact SHA-256 digests')
        self.sources = dict(source_registry)
        self.bars: list[Session] = []
        self.days: dict[date, int] = {}
        self.fact_ids = set()
        self.by_key: dict[tuple, Fact] = {}
        self.proofs: dict[str, list[Fact]] = {}
        self.mothers: dict[str, Mother] = {}
        self.failures: dict[str, Fact] = {}
        self.b1_signals: dict[str, Fact] = {}
        self.launches: dict[str, Launch] = {}
        self.false_breaks: dict[str, Fact] = {}
        self.repairs: dict[str, Repair] = {}
        self.continuations: dict[str, Fact] = {}
        self.continuation_failures: dict[str, Fact] = {}
        self.strong_signals = set()
        self.births: dict[tuple, Fact] = {}

    def _validate(self, bar, facts):
        ids, meanings, births = set(self.fact_ids), dict(self.by_key), dict(self.births)
        for fact in facts:
            if not isinstance(fact, Fact) or not isinstance(fact.kind, Kind) or type(fact.truth) is not bool:
                raise ValueError('Explicit typed evidence required')
            if fact.known_on != bar.day or fact.observed_on > bar.day:
                raise ValueError('Fact does not belong to this known-at D prefix')
            if fact.observed_on not in self.days and fact.observed_on != bar.day:
                raise ValueError('Observed date is absent from this stock-session history')
            if self.sources.get(fact.source_id) != fact.source_sha256:
                raise ValueError('Source identity or SHA is outside the registered authority')
            if not identifier(fact.fact_id) or not identifier(fact.target_id) or fact.fact_id in ids:
                raise ValueError('Fact needs unique ID and explicit target identity')
            ids.add(fact.fact_id)
            meaning_key = (fact.target_id, fact.kind, fact.observed_on)
            old = meanings.get(meaning_key)
            if old and (old.truth, old.info) != (fact.truth, fact.info):
                raise ValueError('Conflicting proof on same event requires source reconciliation')
            meanings[meaning_key] = fact
            if fact.kind in BIRTH_KINDS:
                birth_key = (fact.kind, fact.target_id)
                birth = births.get(birth_key)
                if birth and (birth.observed_on, birth.info) != (fact.observed_on, fact.info):
                    raise ValueError('Event inception identity is immutable, including within a known-at batch')
                births[birth_key] = fact
            if fact.kind is Kind.MOTHER_ATTACK_BUILDUP:
                spec = fact.info
                if (not isinstance(spec, MotherSpec) or not identifier(spec.support_id) or isinstance(spec.failure_level, bool)
                    or not isinstance(spec.failure_level, (int, float)) or not isfinite(spec.failure_level) or spec.failure_level <= 0):
                    raise ValueError('Mother identity requires sourced support ID and positive immutable failure level')
                historic = self.mothers.get(fact.target_id)
                if historic and (historic.origin.observed_on, historic.support_id, historic.failure_level) != (fact.observed_on, spec.support_id, spec.failure_level):
                    raise ValueError('Mother identity immutable')
            elif fact.kind is Kind.M25_DAMAGE:
                spec = fact.info
                if (not isinstance(spec, DamageSpec) or not identifier(spec.lost_structure_id)
                    or spec.previous_repair_id == fact.target_id
                    or any(item is not None and not identifier(item) for item in (spec.root_id, spec.previous_repair_id))):
                    raise ValueError('Damage identity requires explicit root and lost structure references')
                historic = self.repairs.get(fact.target_id)
                if historic and (historic.data.damage.observed_on, historic.data.damage.info) != (fact.observed_on, spec):
                    raise ValueError('Repair identity immutable')
            elif fact.kind is Kind.B2_D0:
                spec = fact.info
                if not isinstance(spec, LaunchSpec) or not identifier(spec.base_id) or (spec.mother_id is not None and not identifier(spec.mother_id)):
                    raise ValueError('D0 requires an independent base identity and optional explicit mother')
            elif fact.kind in (Kind.STRONG_CONTINUATION_CONFIRMED, Kind.M25_ORIGINAL_ROOT_RECLAIMED, Kind.M25_PRIOR_STRUCTURE_RECLAIMED):
                if not identifier(fact.info):
                    raise ValueError('Event needs a separately referenced identity')
            elif fact.kind is Kind.M25_DRAWDOWN_REPORTING:
                if isinstance(fact.info, bool) or not isinstance(fact.info, (int,float)) or not isfinite(fact.info):
                    raise ValueError('Reported damage drawdown must be a finite sourced measurement')
            elif fact.info is not None:
                raise ValueError('Unsupported payload for this proof category')

    def _latest_fact(self, target, kind, *, on=None, after=None, before=None, identity=None):
        candidates = [item for item in self.proofs.get(target, ()) if item.kind is kind
                      and (on is None or item.observed_on == on)
                      and (after is None or item.observed_on > after)
                      and (before is None or item.observed_on < before)
                      and (identity is None or item.info == identity)]
        return max(candidates, key=lambda item: (item.observed_on, item.known_on, item.fact_id), default=None)

    def _test(self, target, kind, **kwargs):
        item = self._latest_fact(target, kind, **kwargs)
        return item.truth if item else None

    def _mother_events(self, facts):
        for item in facts:
            target = item.target_id
            if item.kind is Kind.MOTHER_ATTACK_BUILDUP and target not in self.mothers and item.truth:
                observed = self.bars[self.days[item.observed_on]]
                if observed.close > observed.open:
                    self.mothers[target] = Mother(target, item, item.info.support_id, item.info.failure_level)
        for mother in self.mothers.values():
            if mother.identity in self.failures:
                continue
            applicable = [item for item in self.proofs[mother.identity] if item.kind is Kind.MOTHER_FAILURE and item.truth
                          and item.observed_on >= mother.origin.observed_on]
            if applicable:
                self.failures[mother.identity] = min(applicable,key=lambda item:(item.known_on,item.observed_on,item.fact_id))

    def _b1(self, day, facts, triggers):
        requested = [item.target_id for item in facts if item.kind is Kind.B1_CONFIRM and item.target_id in self.mothers]
        if not self.mothers:
            return None, Path.UNKNOWN, None, None
        results = {}
        triggered = []
        for mother in self.mothers.values():
            identity = mother.identity
            invalidation = self.failures.get(identity)
            if invalidation:
                results[identity] = (mother, Path.INVALIDATED, False, invalidation)
                continue
            past = {'after': mother.origin.observed_on}
            dependencies = conjunction(self._test(identity,Kind.B1_PULLBACK,**past),self._test(identity,Kind.B1_GENUINE_SUPPORT,**past),
                                       self._test(identity,Kind.B1_SUPPLY_DIGESTED,**past))
            confirm = self._latest_fact(identity,Kind.B1_CONFIRM,on=day,**past)
            decision = conjunction(dependencies,confirm.truth if confirm else None)
            if decision is True and identity not in self.b1_signals:
                self.b1_signals[identity] = confirm
                emit(triggers,'B1',confirm,day)
                triggered.append(identity)
            state = self.b1_signals.get(identity)
            results[identity] = (mother,Path.FORMAL,True,None) if state else (mother,evidence_path(decision),decision,None)
        return results[(triggered or requested or list(results))[-1]]

    def _b2(self, bar, facts, triggers):
        day = bar.day
        for item in facts:
            if item.kind is not Kind.B2_D0 or not item.truth or item.target_id in self.launches:
                continue
            spec = item.info
            mother = self.mothers.get(spec.mother_id)
            if item.observed_on != day:
                original = None
            elif bar.close <= bar.open or self._test(item.target_id, Kind.B2_DOWNTREND_REBOUND, on=day) is True:
                original = False
            elif spec.mother_id and (not mother or mother.origin.observed_on >= day):
                original = None
            elif spec.mother_id in self.failures:
                original = False
            else:
                original = conjunction(self._test(spec.base_id, Kind.B2_BASE_CONFIRMED, before=day),
                                       self._test(spec.base_id, Kind.B2_SUPPLY_DIGESTED, before=day),
                                       self._test(item.target_id, Kind.B2_BULLISH_LAUNCH, on=day),
                                       self._test(item.target_id, Kind.B2_ACTUAL_DEPARTURE, on=day))
            self.launches[item.target_id] = Launch(item.target_id, item, spec.base_id, spec.mother_id, original)
            if original is True:
                emit(triggers,'B2_D0',item,day)
        for launch in self.launches.values():
            applicable = [item for item in self.proofs[launch.identity] if item.kind is Kind.B2_NEXT_SESSION_FALSE_BREAK and item.truth
                          and self.days[item.observed_on] == self.days[launch.origin.observed_on] + 1]
            if applicable:
                earliest = min(applicable,key=lambda item:(item.known_on,item.fact_id))
                self.false_breaks.setdefault(launch.identity, earliest)
        requested = [item.target_id for item in facts if item.kind is Kind.B2_RETEST_CONFIRMED and item.target_id in self.launches]
        if not self.launches:
            return None,Path.UNKNOWN,False if bar.close<=bar.open else None,None,None,''
        results = {}
        for launch in self.launches.values():
            false_break = self.false_breaks.get(launch.identity)
            failed_mother = launch.mother_id in self.failures
            today = self._latest_fact(launch.identity,Kind.B2_RETEST_CONFIRMED,on=day,after=launch.origin.observed_on)
            parent = launch.identity if today else ''
            if false_break or failed_mother:
                results[launch.identity] = (launch,Path.INVALIDATED,launch.original_formal,False,false_break,parent)
                continue
            retest = conjunction(launch.original_formal,today.truth if today else None)
            if retest is True:
                emit(triggers,'B2_RETEST',today,day)
            results[launch.identity] = (launch,evidence_path(launch.original_formal),launch.original_formal,retest,None,parent)
        activated = [item['event_id'] for item in triggers if item['method'] in ('B2_D0','B2_RETEST')]
        return results[(activated or requested or list(results))[-1]]

    def _strong(self, day, facts, triggers):
        for item in facts:
            if item.kind is Kind.STRONG_CONTINUATION_CONFIRMED and item.truth:
                self.continuations.setdefault(item.target_id, item)
        for earlier in self.continuations.values():
            applicable = [item for item in self.proofs[earlier.target_id] if item.kind is Kind.STRONG_CONTINUATION_SUPPORT_FAILURE
                          and item.truth and item.observed_on >= earlier.observed_on]
            if applicable:
                earliest = min(applicable,key=lambda item:(item.known_on,item.observed_on,item.fact_id))
                self.continuation_failures.setdefault(earlier.target_id,earliest)
        if not self.continuations:
            return None,Path.UNKNOWN,None,None
        results = {}
        activated = []
        for remembered in self.continuations.values():
            identity = remembered.target_id
            mother = self.mothers.get(remembered.info)
            failure = self.continuation_failures.get(identity) or self.failures.get(remembered.info)
            if failure:
                results[identity] = (remembered,Path.INVALIDATED,False,failure)
            elif not mother or mother.origin.observed_on >= remembered.observed_on:
                results[identity] = (remembered,Path.UNKNOWN,None,None)
            else:
                results[identity] = (remembered,Path.FORMAL,True,None)
                if identity not in self.strong_signals:
                    self.strong_signals.add(identity)
                    emit(triggers,'STRONG_CONTINUATION',remembered,day)
                    activated.append(identity)
        return results[(activated or list(results))[-1]]

    def _new_repair(self, item):
        data = item.info
        previous = self.repairs.get(data.previous_repair_id)
        root = self.mothers.get(data.root_id)
        if data.previous_repair_id and (not previous or previous.data.damage.observed_on >= item.observed_on):
            return Repair(RepairIdentity(item.target_id,item,None,data.lost_structure_id,data.previous_repair_id))
        if previous and previous.data.root and previous.data.root.identity == data.root_id:
            root = previous.data.root
        elif root:
            original_failure = self.failures.get(root.identity)
            if (root.origin.observed_on >= item.observed_on or
                (original_failure and original_failure.observed_on < item.observed_on)):
                root = None
        if previous:
            if previous.test and previous.test.observed_on < item.observed_on and not previous.invalidated:
                previous.invalidated = item
        return Repair(RepairIdentity(item.target_id, item, root, data.lost_structure_id, data.previous_repair_id))

    def _m25(self, day, facts, triggers):
        for item in sorted(facts,key=lambda f:(f.observed_on,f.fact_id)):
            if item.kind is Kind.M25_DAMAGE and item.truth and item.target_id not in self.repairs:
                self.repairs[item.target_id] = self._new_repair(item)
        if not self.repairs:
            return None,Path.UNKNOWN,None,None,None,None,None,'NONE'
        for identity,repair in self.repairs.items():
            if not repair.test and not repair.invalidated:
                tests = [item for item in self.proofs[identity] if item.kind is Kind.M25_TEST and item.truth
                         and item.observed_on > repair.data.damage.observed_on]
                if tests:
                    repair.test = min(tests,key=lambda item:(item.observed_on,item.known_on,item.fact_id))
            if repair.test and not repair.invalidated:
                damage = [item for item in self.proofs[identity] if item.kind is Kind.M25_NEW_DAMAGE and item.truth]
                damage += [other.data.damage for other in self.repairs.values() if other.data.previous_repair_id == identity]
                damage = [item for item in damage if item.observed_on > repair.test.observed_on]
                if damage:
                    repair.invalidated = min(damage,key=lambda item:(item.known_on,item.observed_on,item.fact_id))
            if repair.test and not repair.invalidated and not repair.formal:
                candidates = [item for item in self.proofs[identity] if item.kind is Kind.M25_CONFIRM_C and item.truth
                              and item.observed_on > repair.test.observed_on]
                if candidates:
                    repair.candidate = max(candidates,key=lambda item:(item.observed_on,item.known_on,item.fact_id))
        results = {identity:self._evaluate_repair(day,repair,triggers) for identity,repair in self.repairs.items()}
        priority = [item.target_id for item in facts if item.kind in (Kind.M25_CONFIRM_C,Kind.M25_NEW_DAMAGE) and item.target_id in results]
        activated = [item['event_id'] for item in triggers if item['method']=='M25']
        return results[(activated or priority or list(results))[-1]]

    def _evaluate_repair(self, day, repair, triggers):
        candidate,root = repair.candidate,repair.data.root
        identity = repair.data.identity
        root_reclaimed = self._test(identity,Kind.M25_ORIGINAL_ROOT_RECLAIMED,on=candidate.observed_on,identity=root.identity) if candidate and root else None
        prior_reclaimed = self._test(identity,Kind.M25_PRIOR_STRUCTURE_RECLAIMED,on=candidate.observed_on,identity=repair.data.lost_structure_id) if candidate else None
        risk = self._test(identity,Kind.M25_INDEPENDENT_RISK_CLEAR,on=candidate.observed_on) if candidate else None
        history = True if root and candidate else None
        provenance = (history,root_reclaimed,prior_reclaimed,risk)
        if repair.invalidated:
            return repair,Path.INVALIDATED,False,*provenance,'NONE'
        if not root:
            return repair,Path.UNKNOWN,None,*provenance,'NONE'
        if not candidate:
            return repair,Path.WATCH,None,*provenance,'NONE'
        if repair.formal:
            return repair,Path.FORMAL,True,*provenance,'NONE'
        result = conjunction(history,root_reclaimed,prior_reclaimed,risk)
        if result is True:
            if candidate.observed_on!=day:
                return repair,Path.WATCH,False,*provenance,'LATE_PROOF_NON_ACTIONABLE'
            repair.formal = candidate
            emit(triggers,'M25',candidate,day)
        return repair,evidence_path(result),result,*provenance,'NONE'

    def _literal_raw(self, bar):
        f02 = conjunction(check(lambda b,w:b>w,bar.bbi,bar.w), check(lambda w,y:w>y,bar.w,bar.y), check(lambda j:j<=13,bar.j))
        b1006 = conjunction(check(lambda p:p>=4,bar.pct),check(lambda j:j<55,bar.j))
        previous = self.bars[-2].volume if len(self.bars)>1 else None
        b151 = check(lambda v:bar.volume>1.20*v,previous)
        j_window = [None]*(3-len(self.bars[-3:]))+[b.j for b in self.bars[-3:]]
        previous4 = self.bars[-5:-1]
        mean = sum(b.volume for b in previous4)/4 if len(previous4)==4 else None
        b_f03 = conjunction(disjunction(*(check(lambda j:j<13,j) for j in j_window)),check(lambda m:bar.volume>1.25*m,mean),
                             check(lambda p:p>4,bar.pct),check(lambda j:j<70,bar.j),check(lambda w,y:w>y,bar.w,bar.y))
        return {'b1_f02_raw':status(f02),'b2_oral_raw':'UNKNOWN','b2_b2_1006_raw':status(b1006),'b2_b2_151_raw':status(b151),
                'b2_b2_f03_raw':status(b_f03),'b2_trend_raw':'UNKNOWN_PLACEHOLDER'}

    def advance(self, bar: Session, facts=()):
        if self.bars and bar.day <= self.bars[-1].day:
            raise ValueError('Events require monotonically increasing stock sessions')
        facts = tuple(facts)
        self._validate(bar, facts)
        self.days[bar.day] = len(self.bars)
        self.bars.append(bar)
        for fact in facts:
            self.fact_ids.add(fact.fact_id)
            self.by_key[(fact.target_id,fact.kind,fact.observed_on)] = fact
            self.proofs.setdefault(fact.target_id,[]).append(fact)
            if fact.kind in BIRTH_KINDS:
                self.births[(fact.kind,fact.target_id)] = fact
        self._mother_events(facts)
        triggers = []
        mother,b1_path,b1,b1_fail = self._b1(bar.day,facts,triggers)
        launch,b2_path,b2_d0,b2_retest,b2_fail,retest_parent = self._b2(bar,facts,triggers)
        continuation,strong_path,strong,strong_fail = self._strong(bar.day,facts,triggers)
        repair,m25_path,m25,history,root_reclaimed,lost_reclaimed,risk,late_completion = self._m25(bar.day,facts,triggers)
        root = repair.data.root if repair else None
        root_fail = self.failures.get(root.identity) if root else None
        drawdown = self._latest_fact(repair.data.identity,Kind.M25_DRAWDOWN_REPORTING) if repair else None
        shape = Shape.BULLISH if bar.close>bar.open else Shape.BEARISH if bar.close<bar.open else Shape.FLAT
        ids = {item for item in (mother.identity if mother else '',launch.identity if launch else '',launch.base_id if launch else '',
                                  launch.mother_id if launch else '',continuation.target_id if continuation else '',continuation.info if continuation else '',
                                  repair.data.identity if repair else '',root.identity if root else '',repair.data.previous_repair_id if repair else '') if item}
        ids.update(item['event_id'] for item in triggers)
        relevant = {f.fact_id:f for f in facts}
        for item in ids:
            relevant.update({f.fact_id:f for f in self.proofs.get(item,())})
        refs = [f.reference() for f in sorted(relevant.values(),key=lambda x:(x.known_on,x.observed_on,x.fact_id))]
        return {
            'candle_shape_D':shape.value,**self._literal_raw(bar),
            'b1_path':b1_path.value,'b1_formal':status(b1),'b1_mother_event_id':mother.identity if mother else '',
            'b1_mother_date':fact_day(mother.origin if mother else None),'b1_support_id':mother.support_id if mother else '',
            'b1_immutable_fail_level':mother.failure_level if mother else '', 'b1_invalidation_proof_id':b1_fail.fact_id if b1_fail else '',
            'b1_failure_known_on':b1_fail.known_on.isoformat() if b1_fail else '',
            'b2_path':b2_path.value,'b2_formal_D0':status(b2_d0),'b2_formal_retest':status(b2_retest),
            'b2_D0_observation':'SOURCE_BOUND' if launch else 'BULLISH_SHAPE_ONLY' if shape is Shape.BULLISH else 'NON_BULLISH',
            'b2_D0_event_id':launch.identity if launch else '', 'b2_D0_date':fact_day(launch.origin if launch else None),
            'b2_base_event_id':launch.base_id if launch else '', 'b2_mother_event_id':(launch.mother_id or '') if launch else '',
            'b2_retest_parent_D0_event_id':retest_parent,'b2_false_break_known_on':b2_fail.known_on.isoformat() if b2_fail else '',
            'strong_continuation_path':strong_path.value,'strong_continuation_formal':status(strong),'b3_mapping':'HYPOTHESIS_ONLY',
            'strong_continuation_event_id':continuation.target_id if continuation else '',
            'strong_continuation_mother_event_id':continuation.info if continuation else '',
            'strong_continuation_date':fact_day(continuation),'strong_continuation_invalidation_proof_id':strong_fail.fact_id if strong_fail else '',
            'strong_continuation_failure_known_on':strong_fail.known_on.isoformat() if strong_fail else '',
            'm25_path':m25_path.value,'m25_formal':status(m25),'m25_history_preserved':status(history),
            'm25_damage_observed':'TRUE' if repair else 'UNKNOWN','m25_test_observed':'TRUE' if repair and repair.test else 'UNKNOWN',
            'm25_rebuild_observed':'TRUE' if repair and repair.candidate else 'UNKNOWN',
            'm25_root_reclaimed':status(root_reclaimed),'m25_prior_structure_reclaimed':status(lost_reclaimed),'m25_independent_risk_clear':status(risk),
            'm25_chain_id':repair.data.identity if repair else '', 'm25_original_root_event_id':root.identity if root else '',
            'm25_old_support_id':root.support_id if root else '', 'm25_prior_lost_structure_id':repair.data.lost_structure_id if repair else '',
            'm25_previous_repair_id':(repair.data.previous_repair_id or '') if repair else '',
            'm25_invalidation_proof_id':repair.invalidated.fact_id if repair and repair.invalidated else '',
            'm25_original_root_invalidation_proof_id':root_fail.fact_id if root_fail else '',
            'm25_original_root_invalidation_known_on':root_fail.known_on.isoformat() if root_fail else '',
            'm25_immutable_old_fail_level':root.failure_level if root else '',
            'm25_D_date':fact_day(repair.data.damage if repair else None),'m25_T_date':fact_day(repair.test if repair else None),
            'm25_C_date':fact_day(repair.candidate if repair else None),
            'm25_late_completion_status':late_completion,
            'm25_damage_drawdown_pct_reporting_only':drawdown.info if drawdown and drawdown.truth else '', 'm25_drawdown_role':'REPORTING_ONLY',
            'structure_proof_status':'SOURCE_BOUND' if refs else 'UNBOUND','source_bound_proofs':refs,
            'formal_trigger_methods':sorted({item['method'] for item in triggers}),
            'formal_trigger_events':sorted(triggers,key=lambda item:(item['method'],item['event_id'],item['proof_id'])),
            'formal_chart_eligible':status(bool(triggers)),
        }
