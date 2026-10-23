"""Reconstruct frozen six-field source windows; reanchor before unchanged formula evaluation."""
import os,sys,json,csv,time,math,hashlib,struct,multiprocessing,resource
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
import weekly_compare as w
import numpy as np
import pyarrow.parquet as pq
import pyarrow.dataset as ds
FIELDS=['open','high','low','close','volume','amount']
DTYPE=np.dtype([('date','<u4'),('open','<u4'),('high','<u4'),('low','<u4'),('close','<u4'),('amount','<f4'),('volume','<u4'),('reserved','<u4')])

def day(p,h=None):
 payload=Path(p).read_bytes()
 if h:assert hashlib.sha256(payload).hexdigest()==h,'DAY_SOURCE_DRIFT:'+str(p)
 assert len(payload)%32==0
 a=np.frombuffer(payload,dtype=DTYPE);dates=a['date'].astype('U8');assert list(dates)==sorted(set(dates))
 return {d:{f:float(a[f][i])/(100 if f in FIELDS[:4] else 1) for f in FIELDS} for i,d in enumerate(dates) if d<='20261022'}
def table(spec):
 assert w.sha(spec['path'])==spec['sha256'],'PROJECTION_DRIFT'
 if spec['format']=='csv':
  with Path(spec['path']).open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
 return pq.read_table(spec['path']).to_pylist()
def events(spec):
 p=spec['event_response_path'];assert w.sha(p)==spec['event_response_sha256'],'EVENT_DRIFT'
 j=w.load(p);assert j['response_error'] is None
 out=[];unsupported=[]
 for e in j['response_rows']:
  d='%04d%02d%02d'%(e['year'],e['month'],e['day'])
  if d>'20261022':continue
  if e['category'] in (11,12):unsupported.append(d)
  if e['category']!=1:continue
  cash,rp,bonus,rights=[e[k] for k in ['fenhong','peigujia','songzhuangu','peigu']]
  assert all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 for v in [cash,rp,bonus,rights])
  g=1+bonus/10+rights/10;out.append(dict(date=d,A=1/g,B=(-cash/10+rp*rights/10)/g,G=g))
 out.sort(key=lambda e:e['date']);assert len({e['date'] for e in out})==len(out)
 return out,unsupported

def project(dates,raw,ev,anchor):
 assert dates and dates[-1]==anchor and dates==sorted(set(dates))
 a=np.ones(len(dates));b=np.zeros(len(dates));g=np.ones(len(dates));ds0=np.asarray(dates)
 for e in ev:
  if e['date']>anchor:continue
  mask=ds0<e['date'];a[mask]*=e['A'];b[mask]=b[mask]*e['A']+e['B'];g[mask]*=e['G']
 out={f:raw[f]*a+b if f in FIELDS[:4] else raw[f]*g if f=='volume' else raw[f].copy() for f in FIELDS}
 return out

def reconstruct(code,spec,original,native,c56):
 projected=table(spec);dates=[str(x['trade_date']) for x in projected];assert dates==sorted(set(dates)) and len(dates)==spec['rows'] and dates[0]==spec['first_date'] and dates[-1]=='20261022'
 provenance=[]
 if spec.get('raw_path','').endswith('.day'):
  raw=day(spec['raw_path'],spec['raw_sha256']);provenance.append(dict(path=spec['raw_path'],sha256=spec['raw_sha256'],role='FROZEN64_FULL_RAW'))
 elif spec.get('raw_full_history_path'):
  raw=day(spec['raw_full_history_path'],spec['raw_full_history_sha256']);provenance.append(dict(path=spec['raw_full_history_path'],sha256=spec['raw_full_history_sha256'],role='FROZEN60_FULL_RAW'))
 elif code in c56['input_identity']['codes']:
  p=c56['input_identity']['codes'][code]['full_archive'];h=c56['frozen_source_bindings'][p];raw=day(p,h);provenance.append(dict(path=p,sha256=h,role='FROZEN56_FULL_RAW'))
 else:
  raw={str(r['trade_date']):{f:float(r[f]) if r[f] is not None else float('nan') for f in FIELDS} for r in original};provenance.append(dict(role='ORIGINAL_BOUND_SELECTOR_PREFIX_SIX_FIELDS',rows=len(raw)))
  if spec.get('archive_prefix_native_path'):
   p=spec['archive_prefix_native_path'];h=spec['archive_prefix_native_sha256'];raw.update(day(p,h));provenance.append(dict(path=p,sha256=h,role='FROZEN63_ARCHIVE_PREFIX_COMPLETE_RECORDS'))
  nr=native[code];raw.update(day(nr['path'],nr['sha256']));provenance.append(dict(path=nr['path'],sha256=nr['sha256'],role='ACCEPTED_NATIVE_WINS_ALL_SIX_FIELDS'))
 assert sorted(raw)==dates,'RAW_DATE_WINDOW_PARITY:'+code
 arr={f:np.asarray([raw[d][f] for d in dates],dtype=float) for f in FIELDS}
 ev,unsupported=events(spec);q=project(dates,arr,ev,'20261022')
 for f in FIELDS[:5]:assert np.array_equal(q[f],np.asarray([float(r[f]) for r in projected]),equal_nan=True),'RAW_EVENT_PROJECTION_PARITY:'+code+':'+f
 assert all(np.isfinite(arr[f]).all() for f in FIELDS),'RAW_SIXFIELD_MISSING:'+code
 assert all((arr[f]>0).all() for f in FIELDS[:4]),'RAW_PRICE_INVALID:'+code
 assert (arr['volume']>=0).all() and (arr['amount']>=0).all(),'RAW_AMOUNT_VOLUME_INVALID:'+code
 assert np.all(arr['low']<=np.minimum(arr['open'],arr['close'])) and np.all(np.maximum(arr['open'],arr['close'])<=arr['high']),'RAW_OHLC_GEOMETRY:'+code
 return dates,arr,ev,unsupported,provenance

def evaluate(task):
 code,spec,original,native,c56,b,reuse=task
 a=w.module(b['model_a'],'original_frozen');program=a.compile_original(b['formula_a']);kernel=w.module(b['model_b'],'ten_frozen')
 result=[];binding=None
 try:
  if spec['status'] not in ['READY','READY_WITH_ROUTE_LEVEL_MISSING_FIELDS']:raise ValueError('SOURCE_UNKNOWN:'+spec.get('reason',spec['status']))
  dates,raw,ev,unsupported,provenance=reconstruct(code,spec,original,native,c56)
  binding=dict(code=code,raw_sixfield_sha256=w.digest({'dates':dates,'raw':{k:v.tolist() for k,v in raw.items()}}),events_sha256=w.digest(ev),sources=provenance,rows=len(dates),first_date=dates[0],last_date=dates[-1],parity='EXACT_64_OHLCV_EVENT_PROJECTION',amount_basis='UNADJUSTED_NATIVE_CNY_RETAINED',historical_PIT='CANNOT_CONFIRM')
 except Exception as e:
  if isinstance(e,AssertionError):raise
  dates=[];raw={};ev=[];unsupported=[];reason=str(e)
 for signal,selection in w.DATES:
  common=dict(code=code,name=spec.get('name',''),signal_asof=signal,selection_date=selection,historical_qualification='CANNOT_CONFIRM',input_status=spec['status'],input_source_sha256=spec.get('sha256'),raw_binding_sha256=w.digest(binding) if binding else None)
  if not dates or signal not in dates:
   why=reason if not dates else 'EXACT_SIGNAL_BAR_MISSING_NO_DATE_SUBSTITUTION'
   ra=dict(candidate='UNKNOWN',reason=why,hit_rules=[],unknown_rules=['XG'],terminal_values={})
   rb=dict(candidate='UNKNOWN',reason=why,hit_rules=[],unknown_rules=list(kernel.RULES),rules=[])
   if signal=='20261022':rb=reuse
   result.append(dict(**common,model_a=ra,model_b=rb,history_rows=0,history_start=None,dated_input_sha256=None));continue
  n=dates.index(signal)+1;ds0=dates[:n];r0={f:raw[f][:n] for f in FIELDS};e0=[e for e in ev if e['date']<=signal];q=project(ds0,r0,e0,signal)
  identity=w.digest({'code':code,'dates':ds0,'events':e0,'raw':{f:r0[f].tolist() for f in FIELDS},'adjusted':{f:q[f].tolist() for f in FIELDS}})
  try:
   if any(ds0[0]<d<=signal for d in unsupported):raise ValueError('UNSUPPORTED_SPLIT_EVENT')
   v=a.evaluate(program,{k:q[f] for k,f in [('O','open'),('H','high'),('L','low'),('C','close'),('VOL','volume'),('AMOUNT','amount')]},code)
   vals={k:float(x[-1]) if np.isfinite(x[-1]) else None for k,x in v.items()};x=vals['XG']
   ra=dict(candidate='UNKNOWN' if x is None else 'YES' if x!=0 else 'NO',reason=None if x is not None else 'TERMINAL_NOT_FINITE',hit_rules=[k for k in ['ENTRYPOOL','B2ROLE','B3ROLE','XG'] if vals[k] is not None and vals[k]!=0],unknown_rules=[k for k in ['ENTRYPOOL','B2ROLE','B3ROLE','XG'] if vals[k] is None],terminal_values=vals)
  except Exception as e:ra=dict(candidate='UNKNOWN',reason=type(e).__name__+':'+str(e),hit_rules=[],unknown_rules=['XG'],terminal_values={})
  if signal=='20261022':
   rb=dict(reuse);rb['evaluation_provenance_this_batch']='REUSED_EXACT_65_67_SCOPE_NO_RECALC'
  else:rb=kernel.evaluate_stock(code,ds0,{k:q[f] for k,f in [('C','close'),('H','high'),('L','low'),('VOL','volume')]},signal_date=signal)
  result.append(dict(**common,model_a=ra,model_b=rb,history_rows=n,history_start=ds0[0],dated_input_sha256=identity))
 return dict(code=code,binding=binding,results=result)

def get_tasks(c,codes):
 b=c['input_identity'];m=w.load(b['manifest']);statuses={r['code']:r for r in m['all_input_statuses']};native=w.load(b['native_refs']);c56=w.load(w.R/'event_aware_input_canary_56/CONTRACT.json');reuse={r['code']:r for r in map(json.loads,Path(b['reuse_b_D23']).read_text().splitlines())}
 # Select only input fields and code keys. No target-return or benchmark columns are decoded.
 frame=ds.dataset(b['raw_selector']['path'],format='parquet').scanner(columns=['ts_code','trade_date',*FIELDS],filter=ds.field('ts_code').isin(codes)&(ds.field('trade_date')<='20261022'),use_threads=False).to_table().to_pandas();groups=frame.groupby('ts_code',sort=False)
 return [(code,statuses[code],groups.get_group(code).to_dict('records') if code in groups.groups else [],{code:native[code]} if code in native else {},c56,b,reuse[code]) for code in codes]

def run(cp,phase,workers=2):
 c=w.load(cp)
 for p,h in c['frozen_source_bindings'].items():assert w.sha(p)==h,'SOURCE_DRIFT:'+p
 codes=sorted(r['code'] for r in w.load(c['input_identity']['manifest'])['all_input_statuses'])
 if phase=='canary':codes=['000001.SZ','002335.SZ','300949.SZ','301589.SZ','600872.SH','920003.BJ','300573.SZ','600866.SH','301139.SZ']
 out=w.OUT/phase;out.mkdir(exist_ok=True);start=time.monotonic();tasks=get_tasks(c,codes);chunks=[tasks[i:i+50] for i in range(0,len(tasks),50)];allrows=[]
 with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
  for index,chunk in enumerate(chunks):
   p=out/('part_'+str(index).zfill(3)+'.json')
   if p.exists():rows=w.load(p);assert [r['code'] for r in rows]==[t[0] for t in chunk]
   else:rows=list(pool.map(evaluate,chunk));w.save(p,rows)
   allrows.extend(rows)
   if phase=='full' and (index%10==0 or index==len(chunks)-1):w.register(cp,'CHECKPOINT','WEEK_FULL_'+str(index).zfill(3),[p],dict(processed=len(allrows)),decision='RUNNING_FROZEN_SIGNALS_ONLY')
   print(json.dumps(dict(phase=phase,processed=len(allrows),seconds=round(time.monotonic()-start,1))),flush=True)
 summary=dict(phase=phase,codes=len(codes),rows=sum(len(r['results']) for r in allrows),elapsed_seconds=time.monotonic()-start,workers=workers,parent_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,input_binding_ready=sum(r['binding'] is not None for r in allrows),**w.FLAGS);w.save(out/'SUMMARY.json',summary)
 if phase=='canary':w.register(cp,'CHECKPOINT','WEEK_CANARY',[out/'SUMMARY.json'],summary,decision='ENGINEERING_CANARY_ONLY')
 else:seal(allrows,cp)
 return summary

def seal(allrows,cp):
 d=w.OUT/'signals';d.mkdir();files={};binding=[]
 for r in allrows:
  if r['binding']:binding.append(r['binding'])
 w.save(d/'RAW_INPUT_BINDINGS.json',binding)
 for signal,selection in w.DATES:
  rows=sorted([x for r in allrows for x in r['results'] if x['signal_asof']==signal],key=lambda r:r['code']);assert len(rows)==len({r['code'] for r in rows})==5533
  sd=d/selection;sd.mkdir();ledger=[];long=[]
  for r in rows:
   base={k:v for k,v in r.items() if k not in ['model_a','model_b']}
   for model in ['a','b']:
    z=r['model_'+model];ledger.append(dict(**base,model=model,candidate=z['candidate'],hit_rules='|'.join(z['hit_rules']),unknown_rules='|'.join(z['unknown_rules']),reason=z.get('reason'),post_affine_invalid_counts=json.dumps(z.get('raw_invalid_counts',{})),reuse_provenance=z.get('evaluation_provenance_this_batch','NEW_DATED_INPUT_EVALUATION')))
   for z in r['model_b'].get('rules',[]):long.append(dict(code=r['code'],signal_asof=signal,selection_date=selection,**{k:z[k] for k in ['rule_id','status','value','reason']}))
  w.csvwrite(sd/'YES_NO_UNKNOWN.csv',ledger)
  for model in ['a','b']:
   w.csvwrite(sd/('MODEL_'+model.upper()+'_CANDIDATES.csv'),[r for r in ledger if r['model']==model and r['candidate']=='YES'],list(ledger[0]))
  w.csvwrite(sd/'MODEL_B_ALL_RULES.csv',long)
  with (sd/'MODEL_A_TERMINAL_VALUES.jsonl').open('x') as f:
   for r in rows:f.write(json.dumps(dict(code=r['code'],values=r['model_a']['terminal_values']),ensure_ascii=False,allow_nan=False)+'\n')
 for p in sorted(d.rglob('*')):
  if p.is_file():files[str(p.relative_to(w.OUT))]=w.sha(p)
 w.save(w.OUT/'SIGNALS_SEALED.json',dict(sealed_at=datetime.now(timezone.utc).isoformat(),files=files,source_dates=w.DATES,all_signals_complete=True,benchmark_decoded=False,**w.FLAGS))
 w.register(cp,'CHECKPOINT','WEEK_SIGNALS_SEALED',[w.OUT/'SIGNALS_SEALED.json'],dict(code_dates=5533*6),decision='SIGNALS_SHA_FROZEN_BEFORE_BENCHMARK')

if __name__=='__main__':
 from datetime import datetime,timezone
 import argparse
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['canary','full']);p.add_argument('--contract',required=True);p.add_argument('--workers',type=int,default=2);args=p.parse_args();print(json.dumps(run(Path(args.contract),args.phase,args.workers)),flush=True)
