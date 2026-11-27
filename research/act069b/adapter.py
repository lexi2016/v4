"""D-only primitive evidence over immutable bars and explicitly registered objects."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path


UNKNOWN='UNKNOWN'
CANNOT_CONFIRM='CANNOT_CONFIRM'
EXTERNAL_GAPS=('OFFICIAL_HISTORICAL_ST_SOURCE_UNBOUND','OFFICIAL_HISTORICAL_SUSPENSION_SOURCE_UNBOUND',
               'HISTORICAL_PIT_CANNOT_CONFIRM','EFFECTIVE_EXTERNAL_RISK_SOURCE_UNBOUND')


def iso(value):
    result=date.fromisoformat(value)
    if result.isoformat()!=value:
        raise ValueError('Expected canonical ISO date')
    return result


def sha256(path:Path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def dump(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def valid_id(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9_.:@/-]+',value))


def digest_ok(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[0-9a-f]{64}',value))


@dataclass(frozen=True)
class Bar:
    day:date
    open:float
    high:float
    low:float
    close:float
    volume:float

    @property
    def direction(self):
        return direction(self.close,self.open)

    @classmethod
    def from_row(cls,row):
        values=[float(row[key]) for key in ('open','high','low','close','volume')]
        if not all(map(math.isfinite,values)):
            raise ValueError('Invalid OHLCV source')
        op,hi,lo,cl,vol=values
        if lo<=0 or lo>min(op,cl) or max(op,cl)>hi or vol<0:
            raise ValueError('Invalid OHLCV geometry')
        return cls(iso(row['date']),*values)


def direction(close,op):
    return 'BULLISH' if close>op else 'BEARISH' if close<op else 'FLAT'


def through_bars(path,cutoff):
    with path.open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):
            day=iso(row['date'])
            if day>cutoff:
                raise ValueError(f'Cutoff stock session absent: {cutoff}')
            yield Bar.from_row(row)
            if day==cutoff:
                return
    raise ValueError(f'Cutoff stock session absent: {cutoff}')


class Kind(str,Enum):
    KEY_K='KEY_K'
    TURNING_POINT='TURNING_POINT'
    SUPPORT='SUPPORT'
    SEGMENT='SEGMENT'
    ACT069A_TERMINAL='ACT069A_TERMINAL'


@dataclass(frozen=True)
class Source:
    locator:str
    sha256:str
    types:frozenset[Kind]

    def at(self,selector):
        return f'{self.locator}@sha256:{self.sha256}#{selector}'


@dataclass(frozen=True)
class Envelope:
    object_id:str
    source_id:str
    source_sha256:str
    occurred:date
    first_knowable:date


@dataclass(frozen=True)
class Mark:
    evidence:Envelope
    kind:Kind
    price:float
    price_basis:str


@dataclass(frozen=True)
class Support:
    evidence:Envelope
    lower:float
    upper:float
    price_basis:str


@dataclass(frozen=True)
class Segment:
    evidence:Envelope
    start:date
    end:date


@dataclass(frozen=True)
class Terminal:
    evidence:Envelope
    anchor_id:str
    event_chain_id:str


@dataclass
class SupportHistory:
    visible_from:int
    previous_below:bool|None=None
    has_loss:bool=False
    reclaimed_after_loss:bool=False

    def observe(self,below):
        comparison=self.previous_below
        self.previous_below=below
        if comparison is None:
            return None,None,None
        lost=not comparison and below
        reclaim=comparison and not below
        relose=lost and self.reclaimed_after_loss
        if lost:
            self.has_loss=True
            self.reclaimed_after_loss=False
        elif reclaim and self.has_loss:
            self.reclaimed_after_loss=True
        return lost,reclaim,relose


def valid_price(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def describe_compare(bar,previous):
    return {
        'previous_stock_session':str(previous.day),'previous_close':previous.close,'previous_volume':previous.volume,
        'current_close':bar.close,'current_volume':bar.volume,
        'close_delta':bar.close-previous.close,'volume_delta':bar.volume-previous.volume,
        'close_vs_prior_pct':100*(bar.close/previous.close-1) if previous.close else None,
        'volume_vs_prior_ratio':bar.volume/previous.volume if previous.volume else None,
    }


class Adapter:
    def __init__(self,contract,source_registry=None):
        self.contract=contract
        self.sources=dict(source_registry or {})
        if any(not valid_id(name) or not src.locator or not digest_ok(src.sha256)
               or any(not isinstance(kind,Kind) for kind in src.types) for name,src in self.sources.items()):
            raise ValueError('Evidence authority registry invalid')
        bars=contract['sources']['bars']
        baseline=contract['sources']['prior']
        frozen=contract['sources']['contract']
        self.market=Source(bars['locator'],bars['sha256'],frozenset())
        self.baseline=Source(baseline['locator'],baseline['sha256'],frozenset())
        self.frozen=Source(frozen['locator'],frozen['sha256'],frozenset())
        self.bars=[]
        self.index={}
        self.object_ids=set()
        self.marks={Kind.KEY_K:[],Kind.TURNING_POINT:[]}
        self.supports={}
        self.histories={}
        self.relations={}
        self.segments={}
        self.terminals={}

    def _validate_evidence(self,bar,facts):
        seen=set(self.object_ids)
        previous=self.bars[-1].day if self.bars else None
        for item in facts:
            if not isinstance(item,(Mark,Support,Segment,Terminal)) or not isinstance(item.evidence,Envelope):
                raise ValueError('Typed registered evidence required')
            stamp=item.evidence
            if not valid_id(stamp.object_id) or stamp.object_id in seen:
                raise ValueError('Registered object identity is immutable and unique')
            seen.add(stamp.object_id)
            if stamp.occurred>stamp.first_knowable or stamp.first_knowable>bar.day or (previous is not None and stamp.first_knowable<=previous):
                raise ValueError('Invalid occurrence/first-knowable calendar window')
            kind=item.kind if isinstance(item,Mark) else Kind.SUPPORT if isinstance(item,Support) else Kind.SEGMENT if isinstance(item,Segment) else Kind.ACT069A_TERMINAL
            source=self.sources.get(stamp.source_id)
            if not source or kind not in source.types or stamp.source_sha256!=source.sha256:
                raise ValueError('Registered object requires authorized source purpose and exact digest')
            if isinstance(item,Mark) and (item.kind not in (Kind.KEY_K,Kind.TURNING_POINT) or not valid_price(item.price)
                                          or item.price_basis!=self.contract['price_basis']):
                raise ValueError('Registered mark requires exact role and price in the pinned basis')
            if isinstance(item,Support) and (not valid_price(item.lower) or not valid_price(item.upper) or item.lower>item.upper
                                            or item.price_basis!=self.contract['price_basis']):
                raise ValueError('Support requires a finite positive interval in the pinned price basis')
            if isinstance(item,Segment) and not item.start<=item.end<=stamp.occurred:
                raise ValueError('Registered segment endpoints cross observed evidence')
            if isinstance(item,Terminal) and (not valid_id(item.anchor_id) or not valid_id(item.event_chain_id)):
                raise ValueError('Terminal evidence must bind the exact anchor and chain identities')

    def advance(self,bar,facts=()):
        if self.bars and bar.day<=self.bars[-1].day:
            raise ValueError('Non-monotone stock-session replay')
        facts=tuple(facts)
        self._validate_evidence(bar,facts)
        self.index[bar.day]=len(self.bars)
        self.bars.append(bar)
        for item in facts:
            oid=item.evidence.object_id
            self.object_ids.add(oid)
            if isinstance(item,Mark):
                self.marks[item.kind].append(item)
            elif isinstance(item,Support):
                self.supports[oid]=item
                self.histories[oid]=SupportHistory(self.index[bar.day])
            elif isinstance(item,Segment):
                self.segments[oid]=item
            else:
                self.terminals.setdefault(item.anchor_id,[]).append(item)
        self.relations={oid:self.histories[oid].observe(bar.close<support.lower) for oid,support in self.supports.items()}

    def _fact_locator(self,*registered):
        return '|'.join(self.sources[obj.evidence.source_id].at(f'object={obj.evidence.object_id}') for obj in registered)

    def _row(self,primitive,name,value,locator,*,occurred=None,known=None,gap='',registered=False):
        signal=self.bars[-1].day
        occurred=occurred or signal
        known=known or signal
        if not occurred<=known<=signal:
            raise ValueError('Primitive row crosses known-at D cutoff')
        encoded=('TRUE' if value else 'FALSE') if type(value) is bool else value if isinstance(value,str) else dump(value)
        return dict(zip(self.contract['ledger_fields'],(str(signal),primitive,name,encoded,locator,str(occurred),str(known),gap,
                        'MISSING_SOURCE' if gap else 'REGISTERED_SOURCE' if registered else 'OBSERVED_D_ONLY')))

    def _source_gap(self,primitive,name,reason,value=UNKNOWN,locator=None):
        scope=f'evaluation_asof={self.bars[-1].day};source_binding=unbound'
        return self._row(primitive,name,value,locator or self.frozen.at(scope),gap=reason)

    def _absent(self,primitive,reason):
        return [self._source_gap(primitive,name,reason) for name in self.contract['primitive_fact_names'][primitive]]

    def _object_value(self,item,details):
        stamp=item.evidence
        return {'object_id':stamp.object_id,'occurred':str(stamp.occurred),'first_knowable':str(stamp.first_knowable),**details}

    def _registered(self,primitive,name,item,details):
        return self._row(primitive,name,self._object_value(item,details),self._fact_locator(item),
                         occurred=item.evidence.occurred,known=item.evidence.first_knowable,registered=True)

    def _p1(self,bar,index):
        market=self.market.at(f'stock_session_index={index};date={bar.day}')
        rows=[self._row('P1','candle_direction',bar.direction,market),
              self._row('P1','OHLCV',{k:getattr(bar,k) for k in ('open','high','low','close','volume')},market)]
        if index:
            prior=self.bars[-2]
            locator=self.market.at(f'stock_session_index={index-1}..{index};current={bar.day};prior={prior.day}')
            move=describe_compare(bar,prior)
            rows.append(self._row('P1','prior_session_ohlcv_ref',{'stock_session_index':index-1,'date':str(prior.day),
                                   **{k:getattr(prior,k) for k in ('open','high','low','close','volume')}},
                                  self.market.at(f'stock_session_index={index-1};date={prior.day}'),occurred=prior.day,known=prior.day))
            rows.append(self._comparison_row('P1','close_vs_prior_close_pct',move['close_vs_prior_pct'],locator))
            rows.append(self._comparison_row('P1','volume_vs_prior_session_ratio',move['volume_vs_prior_ratio'],locator))
            delta=move['volume_delta']
            rows.append(self._row('P1','volume_direction_vs_prior','INCREASE' if delta>0 else 'DECREASE' if delta<0 else 'UNCHANGED',locator))
        else:
            rows.extend(self._source_gap('P1',name,'PRIOR_STOCK_SESSION_UNAVAILABLE',locator=market)
                        for name in self.contract['primitive_fact_names']['P1'][2:6])
        for kind,name,gap in ((Kind.KEY_K,'registered_key_k','KEY_K_SOURCE_UNBOUND'),
                              (Kind.TURNING_POINT,'registered_turning_point','TURNING_POINT_SOURCE_UNBOUND')):
            visible=sorted(self.marks[kind],key=lambda item:(item.evidence.occurred,item.evidence.first_knowable,item.evidence.object_id))
            if visible:
                values=[self._object_value(item,{'kind':kind.value,'price':item.price,'price_basis':item.price_basis,
                                                'source_locator':self._fact_locator(item)}) for item in visible]
                rows.append(self._row('P1',name,values,self._fact_locator(*visible),registered=True,
                                      occurred=max(item.evidence.occurred for item in visible),
                                      known=max(item.evidence.first_knowable for item in visible)))
            else:
                rows.append(self._source_gap('P1',name,gap))
        return rows

    def _comparison_row(self,primitive,name,value,locator,*,registered=False):
        return self._source_gap(primitive,name,'ZERO_COMPARISON_DENOMINATOR',locator=locator) if value is None else self._row(primitive,name,value,locator,registered=registered)

    def _p2_p3(self,bar,index,anchor_id):
        support=self.supports.get(anchor_id)
        if not support:
            p3=self._absent('P3','SUPPORT_OBJECT_SOURCE_UNBOUND')
            if not self.terminals.get(anchor_id):
                p3[-1]=self._source_gap('P3','anchored_invalidation','NO_AUTHORIZED_INVALIDATION_EVIDENCE')
            return [*self._absent('P2','SUPPORT_OBJECT_SOURCE_UNBOUND'),*p3]
        lower,upper=support.lower,support.upper
        binding=self._fact_locator(support)
        locator=f'{binding}|{self.market.at(f"stock_session_index={index};date={bar.day}")}'
        items=self._registered('P2','registered_support_object',support,{'lower':lower,'upper':upper,'price_basis':support.price_basis})
        rows=[items]
        relation='BELOW' if bar.close<lower else 'ABOVE' if bar.close>upper else 'WITHIN'
        ref=lower if relation=='BELOW' else upper if relation=='ABOVE' else bar.close
        values={
            'close_distance_to_registered_support_price':bar.close-ref,
            'close_distance_to_registered_support_pct':100*(bar.close/ref-1),
            'close_vs_registered_support_band':relation,
            'range_overlaps_registered_support':bar.low<=upper and bar.high>=lower,
            'intraday_low_below_registered_support':bar.low<lower,
            'close_reclaims_intraday_pierce':bar.low<lower<=bar.close,
        }
        rows.extend(self._row('P2',name,value,locator,registered=True) for name,value in values.items())
        if index:
            prior=self.bars[-2]
            segment_locator=f'{binding}|{self.market.at(f"stock_session_index={index-1}..{index};current={bar.day};prior={prior.day}")}'
            movement=describe_compare(bar,prior)
            movement.update({'anchor_id':anchor_id,'support_lower':lower,'support_upper':upper,'close_distance_to_support':bar.close-ref,
                             'volume_ratio_gap':'ZERO_COMPARISON_DENOMINATOR' if prior.volume==0 else ''})
            rows.append(self._row('P2','support_session_price_and_volume_change',movement,segment_locator,registered=True))
        else:
            segment_locator=locator
            rows.append(self._source_gap('P2','support_session_price_and_volume_change','PRIOR_STOCK_SESSION_UNAVAILABLE',locator=locator))
        geometry={'intraday_low_below_registered_support':bar.low<lower,
                  'intraday_down_pierce_from_open':bar.open>=lower and bar.low<lower,
                  'close_below_registered_support':bar.close<lower}
        rows.extend(self._row('P3',name,value,locator,registered=True) for name,value in geometry.items())
        anchor_start=self.histories[anchor_id].visible_from
        for name,value in zip(('close_loss','reclaim','relose'),self.relations[anchor_id]):
            used=segment_locator if name!='relose' else f'{binding}|{self.market.at(f"stock_session_index={anchor_start}..{index};anchor_visible_prefix;current={bar.day}")}'
            rows.append(self._source_gap('P3',name,'SUPPORT_PREDECESSOR_STATE_UNBOUND',locator=locator) if value is None
                        else self._row('P3',name,value,used,registered=True))
        terminal=min((item for item in self.terminals.get(anchor_id,()) if support.evidence.occurred<=item.evidence.occurred),
                     key=lambda item:(item.evidence.first_knowable,item.evidence.occurred,item.evidence.object_id),default=None)
        if terminal:
            observed=terminal.evidence
            known=max(observed.first_knowable,support.evidence.first_knowable)
            rows.append(self._row('P3','anchored_invalidation',self._object_value(terminal,{
                'state':'INVALIDATED','anchor_id':anchor_id,'event_chain_id':terminal.event_chain_id,
                'first_knowable_with_anchor':str(known)}),self._fact_locator(support,terminal),
                occurred=observed.occurred,known=known,registered=True))
        else:
            rows.append(self._source_gap('P3','anchored_invalidation','NO_AUTHORIZED_INVALIDATION_EVIDENCE',locator=locator))
        return rows

    def _p4(self,segment_id):
        segment=self.segments.get(segment_id)
        if not segment:
            return self._absent('P4','SEGMENT_DEFINITION_SOURCE_UNBOUND')
        rows=[self._registered('P4','registered_segment',segment,{'start':str(segment.start),'end':str(segment.end)})]
        start=self.index.get(segment.start)
        end=self.index.get(segment.end)
        if start is None or end is None:
            rows.extend(self._source_gap('P4',name,'SEGMENT_BAR_COVERAGE_UNBOUND',locator=self._fact_locator(segment))
                        for name in self.contract['primitive_fact_names']['P4'][1:])
            return rows
        sequence=[]
        groups={'BULLISH':[],'BEARISH':[],'FLAT':[]}
        for index in range(start,end+1):
            bar=self.bars[index]
            prev=self.bars[index-1].close if index>start else None
            groups[bar.direction].append(bar.volume)
            sequence.append({'date':str(bar.day),'stock_session_index':index,'candle_direction':bar.direction,
                             'open':bar.open,'close':bar.close,'close_minus_open':bar.close-bar.open,
                             'prior_close':prev,'close_minus_prior_close':bar.close-prev if prev is not None else None,'volume':bar.volume})
        locator=f'{self._fact_locator(segment)}|{self.market.at(f"stock_session_index={start}..{end};segment={start}..{end}")}'
        for name,value in (('chronological_candle_volume',sequence),('up_candle_volume',math.fsum(groups['BULLISH'])),
                           ('down_candle_volume',math.fsum(groups['BEARISH'])),('flat_candle_volume',math.fsum(groups['FLAT']))):
            rows.append(self._row('P4',name,value,locator,occurred=segment.end,known=segment.evidence.first_knowable,registered=True))
        return rows

    def _p5(self,bar,index,invalidation):
        market=self.market.at(f'stock_session_index={index};date={bar.day}')
        previous=self.bars[-2].day if index else None
        rows=[self._row('P5','stock_session_bar_observed',{
                  'stock_session_index':index,'date':str(bar.day),'prior_stock_session':str(previous) if previous else None},market),
              self._row('P5','observation_basis_and_cutoff',{
                  'market':'SZ','symbol':self.contract['symbol'],'source_generation':self.contract['source_generation'],
                  'price_basis':self.contract['price_basis'],'volume_basis':self.contract['volume_basis'],
                  'observations_used_through':str(bar.day),'source_asof_vintage_pit':'CANNOT_CONFIRM'},
                  f'{market}|{self.baseline.at(f"date={bar.day};field=price_basis,volume_basis,historical_pit")}')]
        for name,reason in zip(self.contract['primitive_fact_names']['P5'][2:6],EXTERNAL_GAPS):
            locator=f'{self.frozen.at(f"evaluation_asof={bar.day};source_binding=unbound")}|' \
                    f'{self.baseline.at(f"date={bar.day};fields=historical_pit,source_bound_proofs")}'
            rows.append(self._source_gap('P5',name,reason,CANNOT_CONFIRM if name=='historical_point_in_time_status' else UNKNOWN,locator))
        rows.append({**invalidation,'primitive_id':'P5','fact_name':'source_bound_structural_veto'})
        return rows

    def snapshot(self,*,anchor_id=None,segment_id=None):
        bar=self.bars[-1]
        index=len(self.bars)-1
        support=self._p2_p3(bar,index,anchor_id)
        invalidation=support[-1]
        if invalidation['fact_name']!='anchored_invalidation':
            raise AssertionError('Frozen P3 invalidation row is absent')
        return [*self._p1(bar,index),*support,*self._p4(segment_id),*self._p5(bar,index,invalidation)]

    def compare_day_chain(self,previous,ledger):
        day=self.bars[-1].day
        index=self.index[day]
        candle=self.bars[-1].direction
        eligible='UNKNOWN' if candle=='BULLISH' else 'FALSE'
        reason='B2_FORMAL_EVIDENCE_UNBOUND' if candle=='BULLISH' else 'B2_D0_NON_BULLISH_NECESSARY_CONDITION'
        if previous['date']!=str(day) or int(previous['stock_session_index'])!=index or previous['candle_shape_D']!=candle or previous['b2_formal_D0']!=eligible:
            raise ValueError(f'Independent ACT069A day eligibility or source index mismatch on {day}')
        if any(getattr(self.bars[-1],key)!=float(previous[f'{key}_D']) for key in ('open','high','low','close','volume')):
            raise ValueError(f'Same-source OHLCV mismatch on {day}')
        projected={'signal_date':str(day),'stock_session_index':str(index),'day_eligibility_method':'B2_D0',
                   'day_eligibility':eligible,'day_eligibility_reason':reason,'candle_direction':candle,
                   'event_chain_state_b1':previous['b1_path'],'event_chain_state_b2':previous['b2_path'],
                   'event_chain_state_strong_continuation':previous['strong_continuation_path'],'event_chain_state_m25':previous['m25_path']}
        blocked={row['primitive_id'] for row in ledger if row['handoff_status']=='MISSING_SOURCE'}
        for key in self.contract['primitive_fact_names']:
            projected[f'pending_{key.lower()}']='PENDING_SOURCE' if key in blocked else 'SOURCE_BOUND'
        projected['external_gaps']='|'.join(EXTERNAL_GAPS)
        projected['source_locator']=f'{self.baseline.at(f"date={day};fields=b2_formal_D0,paths")}|{self.market.at(f"stock_session_index={index};date={day}")}'
        return projected
