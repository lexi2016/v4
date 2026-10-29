"""Four native-window behaviors; fixed fake clocks and mocks, no SDK/network/writes."""
from datetime import datetime,timedelta
from pathlib import Path
import importlib.util,sys
import pytest
HERE=Path(__file__).resolve().parents[1]
APP=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-chain-natural-repair-20261029-r3-stage/app')
sys.path.insert(0,str(APP))
spec=importlib.util.spec_from_file_location('native_window_candidate',HERE/'sources/infrastructure/stage_quote_provider.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
EDGE=datetime.fromisoformat('2026-10-29T09:25:00+08:00');DATE='20261029';FLAGS={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
class Clock:
 def __init__(self):self.wall=EDGE;self.sleeps=[]
 def now(self):return self.wall
 def advance(self,value):self.wall+=timedelta(seconds=value)
 def sleep(self,value):self.sleeps.append(value);self.advance(value)
class Primary:
 def __init__(self,clock,make):self.clock=clock;self.make=make;self.calls=[]
 def snapshot(self,symbols,**kwargs):
  self.calls.append(tuple(symbols));start=self.clock.wall;rows,changes,duration=self.make(len(self.calls),tuple(symbols),start)
  self.clock.advance(duration)
  return dict(trade_date=DATE,stage_id='STAGE_0925',source='FUTU_OPEND_READ_ONLY_SNAPSHOT',capture_started_at=start.isoformat(),captured_at=self.clock.wall.isoformat(),rows=rows,**FLAGS)|changes
class EmptyFallback:
 def __init__(self,clock):self.clock=clock;self.calls=[]
 def snapshot(self,symbols,**kwargs):self.calls.append(tuple(symbols));self.clock.advance(.01);raise ValueError('EMPTY_QUOTE_RPC:retained-host')
def row(code,source,price=10):return {'symbol':code,'source_update_time':source.isoformat(),'last_price':price}
def run(clock,primary,fallback,codes=('A.002286',),sleep=None):
 p=M.NativeAOpeningSnapshotProvider(primary=primary,fallback=fallback,now=clock.now,sleep=clock.sleep if sleep is None else sleep)
 return p.snapshot(codes,trade_date=DATE)

def test_first_future_then_timely_valid_only_missing_sh_sz_are_reread():
 clock=Clock();fallback=EmptyFallback(clock)
 def make(call,codes,start):
  if call==1:return [row('A.600252',start),row('A.002286',EDGE+timedelta(minutes=5))],{},.18
  assert codes==('A.002286',)
  return [row('A.002286',start)],{},.08
 primary=Primary(clock,make);out=run(clock,primary,fallback,('A.600252','A.002286','A.920249'))
 assert primary.calls==[('A.600252','A.002286'),('A.002286',)] and fallback.calls==[('A.002286',)]
 assert clock.sleeps==[.5] and out['missing_symbols']==['A.920249']
 assert len(out['rows'])==2 and out['temporal_cutoff_safe'] is True
 assert out['rows'][1]['source_update_time']==(EDGE+timedelta(seconds=.69)).isoformat()
 assert out['rows'][1]['capture_started_at']==(EDGE+timedelta(seconds=.69)).isoformat()
 assert out['rows'][1]['captured_at']==(EDGE+timedelta(seconds=.77)).isoformat()
 assert out['raw_batches'][0]['rows'][1]['source_update_time']==(EDGE+timedelta(minutes=5)).isoformat()
 assert len(out['rejected_rows'])==2 # Original unsupported BJ plus original future row retained.
 assert all(out[k] is False for k in FLAGS)

@pytest.mark.parametrize('invalid',['future','zero','conflict'])
def test_persistent_invalid_stays_rejected_and_only_three_extra_calls(invalid):
 clock=Clock();fallback=EmptyFallback(clock)
 def make(call,codes,start):
  source=EDGE+timedelta(minutes=5) if invalid=='future' else start
  return [row(codes[0],source,0 if invalid=='zero' else 10)],({'production_allowed':True} if invalid=='conflict' else {}),.05
 primary=Primary(clock,make);out=run(clock,primary,fallback)
 assert out['rows']==[] and out['missing_symbols']==['A.002286']
 assert len(primary.calls)==4 and len(fallback.calls)==1 and clock.sleeps==[.5,.5,.5]
 assert out['temporal_cutoff_safe'] is True # Timely failed observations do not become valid market rows.
 assert (len(out['rejected_rows'])==4 if invalid!='conflict' else len([e for e in out['errors'] if 'identity/safety conflict' in e])==4)

@pytest.mark.parametrize('boundary',['insufficient_remaining','overslept','late_return'])
def test_deadline_no_blind_requests_or_late_acceptance(boundary):
 clock=Clock();fallback=EmptyFallback(clock)
 def make(call,codes,start):
  if boundary=='insufficient_remaining':return [row(codes[0],EDGE+timedelta(minutes=5))],{},4.6
  if call==1:return [row(codes[0],EDGE+timedelta(minutes=5))],{},.1
  return [row(codes[0],start)],{},6
 def sleep(value):
  assert value==.5;clock.sleeps.append(value);clock.advance(6 if boundary=='overslept' else value)
 primary=Primary(clock,make);out=run(clock,primary,fallback,sleep=sleep)
 assert out['rows']==[] and len(fallback.calls)==1
 if boundary=='insufficient_remaining':assert len(primary.calls)==1 and clock.sleeps==[]
 elif boundary=='overslept':assert len(primary.calls)==1 and clock.sleeps==[.5] and out['temporal_cutoff_safe'] is False
 else:
  assert len(primary.calls)==2 and clock.sleeps==[.5] and out['temporal_cutoff_safe'] is False
  assert out['raw_batches'][-1]['captured_at']==clock.wall.isoformat()
  assert out['raw_batches'][-1]['rows'][0]['source_update_time']==(EDGE+timedelta(seconds=.61)).isoformat()
  assert out['captured_at']==clock.wall.isoformat() # No late clock rewriting.

def test_first_round_complete_has_no_retry_sleep_or_fallback():
 clock=Clock();fallback=EmptyFallback(clock);primary=Primary(clock,lambda call,codes,start:([row(c,start) for c in codes],{},.1))
 out=run(clock,primary,fallback,('A.002286','A.600252'))
 assert len(primary.calls)==1 and fallback.calls==[] and clock.sleeps==[]
 assert len(out['rows'])==2 and out['missing_symbols']==[] and out['temporal_cutoff_safe'] is True
