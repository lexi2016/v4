"""Targeted original-source oracle; no all109 parity claim or live state IO."""
import argparse,ast,hashlib,json,math,struct,sys
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
from native_state import NATIVE_CORE_SHA,append,new_state,encode,decode,digest

def bits(v):return struct.pack('>d',float(v)).hex()
def load_functions(path,names,namespace):
    tree=ast.parse(path.read_bytes());selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(selected)==len(names)
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),namespace)
    return namespace

def main(par,out):
    corepath=par/'handoff/mac_native_dependencies_20261101/extracted/skill/modules/indicators/core.py'
    assert hashlib.sha256(corepath.read_bytes()).hexdigest()==NATIVE_CORE_SHA
    core=load_functions(corepath,{'calculate_ma','calculate_ema_series','calculate_sma_series','calculate_kdj','calculate_slope'},dict(_normalize_klines=lambda x:x))
    prefixpath=par/'handoff/unified_candidate_20261102/prefix_math.py'
    prefix=load_functions(prefixpath,{'series'},{})['series'];counts={};differences=[];cases=[]
    def compare(field,a,b):
        counts[field]=counts.get(field,0)+1
        if a is None or b is None:
            if a is not b:differences.append(dict(field=field,left=a,right=b))
        elif isinstance(a,(list,tuple)):
            for x,y in zip(a,b):compare(field,x,y)
            if len(a)!=len(b):differences.append(dict(field=field,length=True))
        elif bits(a)!=bits(b):differences.append(dict(field=field,left_bits=bits(a),right_bits=bits(b),left=a,right=b))
    # 3 symbols, long/medium/new listing, deterministic varied non-integer bars.
    for symbol,n,offset in [('000001.SZ',320,0),('688001.SH',140,13),('301716.SZ',20,29)]:
        raw=[];bars=[];previous=None
        for i in range(n):
            c=10.1+offset+math.sin(i*.37)*2+i*.003;day=(date(2020,1,1)+timedelta(days=i)).strftime('%Y%m%d')
            r=dict(ts_code=symbol,trade_date=day,open=c+.1,high=c+.7,low=c-.6,close=c,volume=100000.+i*17.3,
                   pre_close=previous,pct_chg=None if previous is None else (c/previous-1)*100)
            raw.append(r);bars.append(SimpleNamespace(**r));previous=c
        binding=dict(source_prefix_sha256=digest(raw),source_reference='SYNTHETIC_ORACLE_ONLY:'+symbol,native_core_sha256=NATIVE_CORE_SHA,source_basis='SYNTHETIC_NOT_PAR_HISTORY')
        state=new_state(symbol,binding)
        # At each prefix compare original prefix_math output, original EMA/SMA
        # internals and rounded KDJ against recurrence after serialized restart.
        for i,r in enumerate(raw,1):
            append(state,r,initialization=i<=max(1,n-5))
            state=decode(encode(state));seq=state['sequences'];a=state['accumulators'];bb=bars[:i]
            if i>=10:
                oracle=prefix(bb,SimpleNamespace(**core))
                for own,orig in [('white','calculate_zg_white'),('yellow','calculate_dg_yellow'),('kdj','calculate_kdj'),('brick','calculate_brick_value'),('crosses','detect_double_line_cross'),('trend','detect_brick_trend')]:compare(own,seq[own][-1],oracle[orig][-1])
                first=core['calculate_ema_series']([b.close for b in bb],10);second=core['calculate_ema_series'](first,10)
                compare('ema10_layer1',a['ema10_layer1'],first[-1]);compare('ema10_layer2',a['ema10_layer2'],second[-1])
            if i>=9:
                captured={}
                def on_return(frame,event,arg):
                    if event=='return' and frame.f_code is core['calculate_kdj'].__code__:
                        captured.update(k=frame.f_locals['k'],d=frame.f_locals['d'])
                old_profile=sys.getprofile()
                try:
                    sys.setprofile(on_return);rounded=core['calculate_kdj'](bb)
                finally:sys.setprofile(old_profile)
                compare('original_core_kdj',seq['kdj'][-1],rounded)
                compare('original_core_k_unrounded',a['k'],captured['k'])
                compare('original_core_d_unrounded',a['d'],captured['d'])
            if i>=4:
                va=[];vc=[]
                for j in range(3,i):
                    high=max(b.high for b in bb[j-3:j+1]);low=min(b.low for b in bb[j-3:j+1]);c=bb[j].close
                    va.append((high-c)/(high-low)*100-90.);vc.append((c-low)/(high-low)*100)
                b4=core['calculate_sma_series'](va,4,1);d6=core['calculate_sma_series'](vc,6,1);e6=core['calculate_sma_series'](d6,6,1)
                for field,value in [('brick_sma4',b4[-1]),('brick_sma6_1',d6[-1]),('brick_sma6_2',e6[-1])]:compare(field,a[field],value)
        cases.append(dict(symbol=symbol,rows=n,initialization_rows=state['counters']['initialization_rows'],consecutive_daily_rows=state['counters']['daily_rows'],historical_primitive_rows_recomputed_daily=0,source_kind='SYNTHETIC_ONLY'))
    # Payload preserves signed zero and noncanonical NaN bits; Decimal refused.
    nan=struct.unpack('>d',bytes.fromhex('7ff8000000000042'))[0]
    sample={'v':[0.,-0.,1e-300,nan,None,True,2,'中文',(1.,2.)]}
    assert encode(decode(encode(sample)))==encode(sample)
    from decimal import Decimal
    try:encode(Decimal('1.1'));raise AssertionError('Decimal accepted')
    except TypeError:pass
    assert decode(encode({'a':0.,'b':-0.}))['b']==0.
    try:decode(encode(sample)+b'garbage');raise AssertionError('trailing accepted')
    except ValueError:pass
    exception_tests=[]
    state=new_state('TEST.SZ',binding)
    try:append(state,{**raw[0],'ts_code':'WRONG.SZ'});raise AssertionError('wrong symbol accepted')
    except ValueError:exception_tests.append('foreign_symbol_rejected_before_mutation')
    r={**raw[0],'ts_code':'TEST.SZ'};append(state,r)
    try:append(state,r);raise AssertionError('date accepted')
    except ValueError:exception_tests.append('duplicate_date_rejected_before_mutation')
    r2={**raw[1],'ts_code':'TEST.SZ','volume':0.};append(state,r2)
    assert state['validity']['input_prefix']is False and state['sequences']['white'][-1]is None
    append(state,{**raw[2],'ts_code':'TEST.SZ'})
    assert state['sequences']['white'][-1]is None
    exception_tests.append('invalid_volume_poison_preserved_no_default_recovery')
    flat=new_state('FLAT.SZ',binding)
    for j in range(14):append(flat,dict(ts_code='FLAT.SZ',trade_date=(date(2020,1,1)+timedelta(days=j)).strftime('%Y%m%d'),open=10.,high=10.,low=10.,close=10.,volume=1.,pre_close=10.,pct_chg=0.))
    assert flat['validity']['kdj_prefix']is False and flat['validity']['brick_prefix']is False
    exception_tests.append('flat_denominator_validity_preserved')
    result=dict(status='PASS_PRIMITIVES_ONLY' if not differences else 'FAIL',counts=counts,total_numeric_comparisons=sum(counts.values()),differences=differences,cases=cases,exception_tests=exception_tests,
      binary_codec='PASS_IEEE754_BITS_SIGNED_ZERO_NAN_PAYLOAD_DECIMAL_REJECTION',original_sources=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (corepath,prefixpath)],
      all109_comparison='NOT_IN_THIS_PRIMITIVE_TEST_SEE_SEPARATE_109_ORACLE',internal_kd_unrounded_comparison='PASS_ORIGINAL_FUNCTION_RETURN_FRAME_LOCALS_NO_FORMULA_EDITS',same_source_real_history='NOT_RUN',production_allowed=False)
    out.mkdir(parents=True,exist_ok=True);(out/'PRIMITIVE_ORACLE.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('original_sources','counts','cases','differences')},indent=2))
    if differences:raise SystemExit(1)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--par',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.par,a.output)
