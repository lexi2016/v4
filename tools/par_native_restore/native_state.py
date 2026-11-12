"""New recovery products for pinned Par native float64 primitives.

This module is diagnostic only: it is not a complete Par109 detector recurrence
and must not be used to admit a stock or overwrite historical originals.
Operation order follows the supplied native Python core, not V4 or Decimal51.
Full raw rows and primitive sequences remain available until detector closure.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import struct
from pathlib import Path

SCHEMA = 'par.native.float64.recovery.diagnostic.v1'
NATIVE_CORE_SHA = '8423882092943a11d92b125e2834ef50641053faf984b4592cd12ff599a6c4c7'
IMPLEMENTATION_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def encode(value):
    """Typed, deterministic binary encoding; float payloads are raw IEEE754 >d.

    No pickle, Decimal conversion, JSON float formatting or NaN normalization.
    Dict keys must be strings. Integer and string lengths are unsigned >Q.
    """
    def part(tag, data):
        return tag + struct.pack('>Q', len(data)) + data
    if value is None:return b'n'
    if type(value) is bool:return b't' if value else b'f'
    if type(value) is float:return b'd'+struct.pack('>d',value)
    if type(value) is int:return part(b'i',str(value).encode('ascii'))
    if type(value) is str:return part(b's',value.encode('utf-8'))
    if type(value) in (list,tuple):
        return (b'l' if type(value) is list else b'u')+struct.pack('>Q',len(value))+b''.join(encode(x) for x in value)
    if type(value) is dict and all(type(k) is str for k in value):
        return b'o'+struct.pack('>Q',len(value))+b''.join(encode(k)+encode(v) for k,v in sorted(value.items()))
    raise TypeError('Unsupported state value; no implicit numeric conversion: '+type(value).__name__)


def decode(data):
    position=0
    def take(n):
        nonlocal position
        if n<0 or position+n>len(data):raise ValueError('TRUNCATED_PAYLOAD')
        x=data[position:position+n];position+=n;return x
    def size():return struct.unpack('>Q',take(8))[0]
    def read():
        tag=take(1)
        if tag==b'n':return None
        if tag in (b't',b'f'):return tag==b't'
        if tag==b'd':return struct.unpack('>d',take(8))[0]
        if tag==b'i':return int(take(size()).decode('ascii'))
        if tag==b's':return take(size()).decode('utf-8')
        if tag in (b'l',b'u'):
            seq=[read() for _ in range(size())];return seq if tag==b'l' else tuple(seq)
        if tag==b'o':
            out={}
            for _ in range(size()):
                k=read()
                if type(k) is not str or k in out:raise ValueError('INVALID_OR_DUPLICATE_KEY')
                out[k]=read()
            return out
        raise ValueError('INVALID_TAG')
    value=read()
    if position!=len(data):raise ValueError('TRAILING_BYTES')
    return value


def new_state(symbol, binding):
    required={'source_prefix_sha256','source_reference','native_core_sha256','source_basis'}
    if not required<=binding.keys() or binding['native_core_sha256']!=NATIVE_CORE_SHA:
        raise ValueError('EXPLICIT_SOURCE_BINDINGS_REQUIRED')
    if any(not isinstance(binding[k],str) or not binding[k] for k in required):
        raise ValueError('EXPLICIT_SOURCE_BINDINGS_REQUIRED')
    return dict(schema=SCHEMA,implementation_sha256=IMPLEMENTATION_SHA256,product_kind='NEW_RECOVERY_PRODUCT_NOT_HISTORIC_ORIGINAL',symbol=symbol,
      binding=deepcopy(binding),count=0,first_date=None,last_date=None,pre_close=None,
      accumulators=dict(ema10_layer1=None,ema10_layer2=None,k=50.,d=50.,brick_sma4=None,brick_sma6_1=None,brick_sma6_2=None),
      validity=dict(input_prefix=True,kdj_prefix=True,brick_prefix=True),validity_history=[],raw_prefix=[],
      sequences={k:[] for k in ('ema10_layer1','ema10_layer2','white','yellow','ming','kdj','brick','brick_sma4','brick_sma6_1','brick_sma6_2','crosses','trend')},
      detector_dependency_closed=False,all109_ready=False,RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,
      counters=dict(initialization_rows=0,daily_rows=0,historical_rows_recomputed_daily=0))


def _smooth(old,value,n):
    weight=1/n
    return value if old is None else value*weight+old*(1-weight)


def append(state, row, *, initialization=False):
    """Append one row without re-evaluating any historical primitive sequence.

    Caller owns original prefix authentication. Full rows are retained because
    absence of a detector dependency proof must not silently truncate history.
    """
    if state['schema']!=SCHEMA or state['all109_ready'] or state['implementation_sha256']!=IMPLEMENTATION_SHA256:raise ValueError('DIAGNOSTIC_SCHEMA')
    if row['ts_code']!=state['symbol']:raise ValueError('SYMBOL_MISMATCH')
    day=row['trade_date'];datetime.strptime(day,'%Y%m%d')
    if len(day)!=8 or state['last_date'] is not None and day<=state['last_date']:raise ValueError('DATE_ORDER')
    # Fail before mutation on missing/nonbinary numeric input. Invalid finite
    # OHLCV is retained and marked; it is never replaced with a valid default.
    for key in ('open','high','low','close','volume'):
        if row[key] is not None and (type(row[key]) not in (float,int) or isinstance(row[key],bool)):raise ValueError('NATIVE_NUMERIC_INPUT_REQUIRED')
    r=deepcopy(row);a=state['accumulators'];seq=state['sequences'];i=state['count']
    state['raw_prefix'].append(r);bars=state['raw_prefix'];c=r['close']
    o,h,l,c,v=(None if r[k] is None else float(r[k]) for k in ('open','high','low','close','volume'))
    good=all(x is not None and math.isfinite(x) and x>0 for x in (o,h,l,c,v)) and l<=min(o,c)<=max(o,c)<=h
    if i:good=good and type(r.get('pct_chg')) in (float,int) and math.isfinite(r['pct_chg']) and type(r.get('pre_close')) in (float,int) and r['pre_close']>0
    state['validity']['input_prefix'] &= good
    if not state['validity']['input_prefix']:
        # Original native adapter stops its numeric precompute at first invalid
        # row. Do not invent native arithmetic on a poisoned suffix.
        for values in seq.values():values.append(None)
    else:
        weight=2/11
        a['ema10_layer1']=c if a['ema10_layer1'] is None else c*weight+a['ema10_layer1']*(1-weight)
        one=a['ema10_layer1'];a['ema10_layer2']=one if a['ema10_layer2'] is None else one*weight+a['ema10_layer2']*(1-weight)
        for key in ('ema10_layer1','ema10_layer2'):seq[key].append(a[key])
        seq['white'].append(round(a['ema10_layer2'],2) if i>=9 else 0)
        closes=[b['close'] for b in bars[-114:]]
        ming=0 if i<113 else sum(sum(closes[-p:])/p for p in (14,28,57,114))/4
        seq['ming'].append(ming);seq['yellow'].append(round(ming,2) if i>=113 else 0)
        if i>=8:
            low=min(b['low'] for b in bars[-9:]);high=max(b['high'] for b in bars[-9:])
            state['validity']['kdj_prefix'] &= high>low
            rsv=50. if high==low else (c-low)/(high-low)*100
            a['k']=(2/3)*a['k']+(1/3)*rsv;a['d']=(2/3)*a['d']+(1/3)*a['k']
        seq['kdj'].append((round(a['k'],2),round(a['d'],2),round(3*a['k']-2*a['d'],2)) if i>=8 else (50,50,50))
        if i>=3:
            high=max(b['high'] for b in bars[-4:]);low=min(b['low'] for b in bars[-4:]);state['validity']['brick_prefix'] &= high>low
            va=-90. if high==low else (high-c)/(high-low)*100-90.
            vc=50. if high==low else (c-low)/(high-low)*100
            a['brick_sma4']=_smooth(a['brick_sma4'],va,4)
            a['brick_sma6_1']=_smooth(a['brick_sma6_1'],vc,6)
            a['brick_sma6_2']=_smooth(a['brick_sma6_2'],a['brick_sma6_1'],6)
        for key in ('brick_sma4','brick_sma6_1','brick_sma6_2'):seq[key].append(a[key])
        brick=0
        if i>=11:
            value=(a['brick_sma6_2']+100)-(a['brick_sma4']+100);brick=round(value-4 if value>4 else 0,2)
        seq['brick'].append(brick)
        seq['crosses'].append((False,False) if i<115 else (seq['white'][-2]<=seq['yellow'][-2] and seq['white'][-1]>seq['yellow'][-1],seq['white'][-2]>=seq['yellow'][-2] and seq['white'][-1]<seq['yellow'][-1]))
        seq['trend'].append(False if i<120 else _slope(seq['ming'][113:],7)>-.02 and seq['white'][-1]>ming)
    state['validity_history'].append(tuple(state['validity'][k] for k in ('input_prefix','kdj_prefix','brick_prefix')))
    state['count']+=1;state['first_date']=state['first_date'] or day;state['last_date']=day;state['pre_close']=r['close']
    state['counters']['initialization_rows' if initialization else 'daily_rows']+=1
    return state


def _slope(values,period):
    # Same operation order as pinned core.calculate_slope, bounded final7 values.
    if len(values)<period:period=len(values)
    if period<2:return 0
    recent=values[-period:];n=period
    sum_x=n*(n-1)/2;sum_xx=(n-1)*n*(2*n-1)/6
    sum_y=sum(recent);sum_xy=sum(recent[i]*i for i in range(n))
    denominator=n*sum_xx-sum_x*sum_x
    if denominator==0:return 0
    return (n*sum_xy-sum_x*sum_y)/denominator
