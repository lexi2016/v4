"""Independent frozen-scope verifier. Reads full ledgers/rankings, replays bounded samples only."""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,math,os,sys,time
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
sys.dont_write_bytecode=True
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def canon(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def csvrows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m

def assert_compact_unknown(row,spec,rule_ids,available_dates=None):
 """Allow omitted rule rows only for explicit unavailable source or exact dated bar."""
 assert row['candidate']=='UNKNOWN','EMPTY_RULES_REQUIRE_UNKNOWN'
 assert row['hit_rules']=='','EMPTY_RULES_CANNOT_HAVE_HITS'
 assert row['unknown_rules'].split('|')==list(rule_ids),'EMPTY_RULES_REQUIRE_ALL_TEN_UNKNOWN'
 assert int(row['history_rows'])==0 and not row['history_start'] and not row['dated_input_sha256'],'EMPTY_RULES_REQUIRE_NO_EVALUATED_HISTORY'
 assert row['input_status']==spec['status'],'EMPTY_RULES_SOURCE_STATUS_DRIFT'
 reason=row['reason']
 if spec['status']=='CANNOT_CONFIRM':
  assert reason=='SOURCE_UNKNOWN:'+spec.get('reason',spec['status']),'EMPTY_RULES_SOURCE_REASON_UNBOUND'
  return 'SOURCE_UNAVAILABLE'
 assert spec['status'] in ['READY','READY_WITH_ROUTE_LEVEL_MISSING_FIELDS'],'EMPTY_RULES_UNSUPPORTED_SOURCE_STATUS'
 assert reason=='EXACT_SIGNAL_BAR_MISSING_NO_DATE_SUBSTITUTION','EMPTY_RULES_DATED_REASON_REQUIRED'
 assert available_dates is not None and row['signal_asof'] not in available_dates,'EMPTY_RULES_SIGNAL_BAR_ACTUALLY_EXISTS'
 return 'EXACT_SIGNAL_BAR_UNAVAILABLE'

def main(cp):
 c=load(cp);assert Path(sys.executable).resolve()==Path(c['runtime']['python_executable']).resolve(),'REVIEW_RUNTIME_DRIFT';d=Path(c['artifact_root']);out=Path(c['review_output']);out.mkdir(exist_ok=True);started=datetime.now(timezone.utc).isoformat();t=time.monotonic()
 for p,h in c['frozen_source_bindings'].items():assert sha(p)==h,'FROZEN_BINDING_DRIFT:'+p
 found=[]
 with Path(c['registry_path']).open() as f:
  for line in f:
   e=json.loads(line)
   if e['execution_id']==c['execution_id']:found.append(e)
 assert len(found)==1 and found[0]['event_type']=='RUN_STARTED' and found[0]['contract_sha256']==sha(cp),'OFFICIAL_REVIEW_START_REQUIRED'
 def fence(event,args):
  if event.startswith(('socket.connect','socket.bind','subprocess.Popen','sqlite3.connect')):raise RuntimeError('READ_ONLY_OFFLINE_REVIEW')
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
   p=Path(os.fsdecode(args[0])).resolve();assert out.resolve() in p.parents,'REVIEW_OUTPUT_ONLY'
 sys.addaudithook(fence)
 import numpy as np,pyarrow.dataset as ds,pyarrow.parquet as pq
 b=c['input_identity'];panel_stat=Path(b['raw_selector']['path']).stat();assert {'inode':panel_stat.st_ino,'mtime_ns':panel_stat.st_mtime_ns,'size_bytes':panel_stat.st_size}==b['raw_selector']['stat'],'SELECTOR_FAST_BIND_DRIFT';m=load(b['manifest']);specs={r['code']:r for r in m['all_input_statuses']};codes=sorted(specs);assert len(codes)==5533
 dates=c['dates'];seal=load(d/'SIGNALS_SEALED.json');assert seal['all_signals_complete'] and not seal['benchmark_decoded']
 for p,h in seal['files'].items():assert sha(d/p)==h,'SEALED_SIGNAL_DRIFT:'+p
 receipt=load(d/'RESULT_RECEIPT.json');assert seal['sealed_at']<receipt['benchmark_started'] and receipt['signals_seal_sha256']==sha(d/'SIGNALS_SEALED.json'),'SIGNALS_NOT_SEALED_BEFORE_BENCHMARK'
 for p,h in receipt['benchmark_files'].items():assert sha(d/p)==h,'BENCHMARK_FILE_DRIFT:'+p
 a=mod(b['model_a'],'independent_original');program=a.compile_original(b['formula_a']);k=mod(b['model_b'],'independent_ten');writer_engine=mod(c['engine_source'],'writer_engine_boundary_only')
 source56=load(c['contract56']);native=load(b['native_refs']);dtype=np.dtype([('date','<u4'),('open','<u4'),('high','<u4'),('low','<u4'),('close','<u4'),('amount','<f4'),('volume','<u4'),('reserved','<u4')]);fields=['open','high','low','close','volume','amount'];day_cache={};event_cache={}
 def day(path,h):
  if path in day_cache:return day_cache[path]
  payload=Path(path).read_bytes();assert hashlib.sha256(payload).hexdigest()==h,'RAW_FILE_DRIFT';assert len(payload)%32==0
  q=np.frombuffer(payload,dtype=dtype);dd=q['date'].astype('U8');assert list(dd)==sorted(set(dd));answer={date:{f:float(q[f][i])/(100 if f in fields[:4] else 1) for f in fields} for i,date in enumerate(dd) if date<='20261022'};day_cache[path]=answer;return answer
 def ev(spec):
  code=spec['code']
  if code in event_cache:return event_cache[code]
  assert sha(spec['event_response_path'])==spec['event_response_sha256'];capture=load(spec['event_response_path']);assert capture['response_error'] is None;answer=[];unsupported=[]
  for e in capture['response_rows']:
   date='%04d%02d%02d'%(e['year'],e['month'],e['day'])
   if date>'20261022':continue
   if e['category'] in (11,12):unsupported.append(date)
   if e['category']!=1:continue
   cash,rp,bonus,rights=[e[f] for f in ['fenhong','peigujia','songzhuangu','peigu']];g=1+bonus/10+rights/10
   assert g>0 and all(math.isfinite(v) and v>=0 for v in [cash,rp,bonus,rights]);answer.append(dict(date=date,A=1/g,B=(-cash/10+rp*rights/10)/g,G=g))
  answer.sort(key=lambda r:r['date']);assert len({r['date'] for r in answer})==len(answer);event_cache[code]=(answer,unsupported);return answer,unsupported
 def direct_raw(code,spec):
  if spec.get('raw_path','').endswith('.day'):return day(spec['raw_path'],spec['raw_sha256'])
  if spec.get('raw_full_history_path'):return day(spec['raw_full_history_path'],spec['raw_full_history_sha256'])
  if code in source56['input_identity']['codes']:
   p=source56['input_identity']['codes'][code]['full_archive'];return day(p,source56['frozen_source_bindings'][p])
  r=native[code];return day(r['path'],r['sha256'])
 # Full ledger and candidate accounting. Missing long-table rows are restored only from explicit UNKNOWNs.
 date_key_cache={}
 def source_date_keys(spec):
  if spec['code'] not in date_key_cache:
   assert sha(spec['path'])==spec['sha256'],'SOURCE_DATE_METADATA_DRIFT'
   if spec['format']=='parquet':keys=pq.read_table(spec['path'],columns=['trade_date']).column('trade_date').to_pylist()
   else:keys=[r['trade_date'] for r in csvrows(spec['path'])]
   keys=[str(x) for x in keys];assert keys==sorted(set(keys)) and len(keys)==spec['rows'],'SOURCE_DATE_KEY_IDENTITY'
   date_key_cache[spec['code']]=set(keys)
  return date_key_cache[spec['code']]
 ledger={};avalues={};rulemap={};samples={'002388.SZ','000001.SZ','002335.SZ','300949.SZ','301589.SZ','600872.SH','920003.BJ','300573.SZ','600866.SH','301139.SZ','603007.SH'};expanded_missing={};missing_rule_causes={};counts=[]
 for signal,selection in dates:
  sd=d/'signals'/selection;rows=csvrows(sd/'YES_NO_UNKNOWN.csv');index={(r['code'],r['model']):r for r in rows};assert len(rows)==len(index)==11066 and {r['code'] for r in rows}==set(codes)
  assert all(r['selection_date']==selection and r['signal_asof']==signal and r['candidate'] in ['YES','NO','UNKNOWN'] for r in rows)
  for model in ['a','b']:
   actual=csvrows(sd/('MODEL_'+model.upper()+'_CANDIDATES.csv'));expected=[r for r in rows if r['model']==model and r['candidate']=='YES'];assert actual==expected and [r['code'] for r in actual]==sorted(r['code'] for r in actual)
   for state in ['YES','NO','UNKNOWN']:
    pool=sorted(r['code'] for r in rows if r['model']==model and r['candidate']==state)
    samples.update(pool[:2])
  values={r['code']:r['values'] for r in map(json.loads,(sd/'MODEL_A_TERMINAL_VALUES.jsonl').read_text().splitlines())};assert set(values)==set(codes)
  for code,v in values.items():
   status=index[(code,'a')]['candidate'];assert status==('UNKNOWN' if not v or v.get('XG') is None else 'YES' if v['XG']!=0 else 'NO')
  long=csvrows(sd/'MODEL_B_ALL_RULES.csv');rm={(r['code'],r['rule_id']):r for r in long};assert len(rm)==len(long);missing=[];missing_causes={}
  for code in codes:
   r=index[(code,'b')];rr=[rm.get((code,rid)) for rid in k.RULES]
   if not any(rr):
    proof_dates=source_date_keys(specs[code]) if specs[code]['status'] in ['READY','READY_WITH_ROUTE_LEVEL_MISSING_FIELDS'] else None
    missing_causes[code]=assert_compact_unknown(r,specs[code],k.RULES,proof_dates)
    missing.append(code)
    for rid in k.RULES:rm[(code,rid)]=dict(code=code,rule_id=rid,status='DATA_UNAVAILABLE',value='',reason=r['reason'])
   else:assert all(rr),'PARTIAL_RULE_ROW_SET'
   hits=[rid for rid in k.RULES if rm[(code,rid)]['status']=='TRIGGERED'];unknown=[rid for rid in k.RULES if rm[(code,rid)]['status']=='DATA_UNAVAILABLE'];assert r['hit_rules'].split('|')==(hits or ['']) and r['unknown_rules'].split('|')==(unknown or [''])
   assert r['candidate']==('YES' if hits else 'UNKNOWN' if unknown else 'NO')
  assert len(rm)==55330;expanded_missing[selection]=missing;missing_rule_causes[selection]=missing_causes;ledger[selection]=index;avalues[selection]=values;rulemap[selection]=rm
  counts.append(dict(selection_date=selection,a=dict(Counter(r['candidate'] for r in rows if r['model']=='a')),b=dict(Counter(r['candidate'] for r in rows if r['model']=='b'))))
 # R1's actual 002388 case is valid UNKNOWN only with independently read missing-date proof.
 regression_row=ledger['20261016'][('002388.SZ','b')];regression_spec=specs['002388.SZ'];regression_dates=source_date_keys(regression_spec)
 assert regression_spec['status']=='READY' and regression_row['signal_asof']=='20261015'
 assert assert_compact_unknown(regression_row,regression_spec,k.RULES,regression_dates)=='EXACT_SIGNAL_BAR_UNAVAILABLE'
 regression_negative_cases=0
 bad_cases=[dict(regression_row,candidate='NO'),dict(regression_row,reason='UNEXPLAINED_UNKNOWN'),dict(regression_row,unknown_rules='|'.join(list(k.RULES)[:-1]))]
 for bad in bad_cases:
  try:assert_compact_unknown(bad,regression_spec,k.RULES,regression_dates)
  except AssertionError:regression_negative_cases+=1
  else:raise AssertionError('COMPACT_UNKNOWN_INVALID_METADATA_ACCEPTED')
 try:assert_compact_unknown(regression_row,regression_spec,k.RULES,regression_dates|{'20261015'})
 except AssertionError:regression_negative_cases+=1
 else:raise AssertionError('COMPACT_UNKNOWN_WITH_PRESENT_SIGNAL_ACCEPTED')
 reuse={r['code']:r for r in map(json.loads,Path(b['reuse_b_D23']).read_text().splitlines())}
 for code in codes:
  r=ledger['20261023'][(code,'b')];prior=reuse[code];assert r['candidate']==prior['candidate'] and r['hit_rules']=='|'.join(prior['hit_rules']) and r['unknown_rules']=='|'.join(prior['unknown_rules'])
 # Independent six-field reconstruction on representative code/source/outcome branches only.
 sample_codes=sorted(code for code in samples if code in m['catalog']);frame=ds.dataset(b['raw_selector']['path'],format='parquet').scanner(columns=['ts_code','trade_date',*fields],filter=ds.field('ts_code').isin(sample_codes)&(ds.field('trade_date')<='20261022'),use_threads=False).to_table().to_pandas();groups=frame.groupby('ts_code',sort=False);replays=0;negative_checks=0;sample_bindings=[]
 for code in sample_codes:
  spec=specs[code];rows=pq.read_table(spec['path']).to_pylist() if spec['format']=='parquet' else csvrows(spec['path']);dd=[str(r['trade_date']) for r in rows]
  if spec.get('raw_path','').endswith('.day') or spec.get('raw_full_history_path') or code in source56['input_identity']['codes']:raw=dict(direct_raw(code,spec))
  else:
   raw={str(r['trade_date']):{f:float(r[f]) if r[f] is not None else np.nan for f in fields} for r in groups.get_group(code).to_dict('records')}
   if spec.get('archive_prefix_native_path'):raw.update(day(spec['archive_prefix_native_path'],spec['archive_prefix_native_sha256']))
   raw.update(direct_raw(code,spec))
  assert sorted(raw)==dd and len(dd)==spec['rows'];events,unsupported=ev(spec);arrays={f:np.asarray([raw[date][f] for date in dd]) for f in fields}
  assert all(np.isfinite(v).all() for v in arrays.values());assert all((arrays[f]>0).all() for f in fields[:4]);assert (arrays['volume']>=0).all() and (arrays['amount']>=0).all();assert np.all(arrays['low']<=np.minimum(arrays['open'],arrays['close'])) and np.all(np.maximum(arrays['open'],arrays['close'])<=arrays['high'])
  def adjusted(bound_dates,bound_raw,bound_events,anchor):
   A=np.ones(len(bound_dates));B=np.zeros(len(bound_dates));G=np.ones(len(bound_dates));da=np.asarray(bound_dates)
   for event in bound_events:
    assert event['date']<=anchor
    mask=da<event['date'];A[mask]*=event['A'];B[mask]=B[mask]*event['A']+event['B'];G[mask]*=event['G']
   return {f:bound_raw[f]*A+B if f in fields[:4] else bound_raw[f]*G if f=='volume' else bound_raw[f].copy() for f in fields}
  q22=adjusted(dd,arrays,events,'20261022')
  for f in fields[:5]:assert np.array_equal(q22[f],np.asarray([float(r[f]) for r in rows]),equal_nan=True),'SAMPLE_SOURCE_PARITY:'+code+':'+f
  for signal,selection in dates:
   if signal not in dd:
    assert ledger[selection][(code,'a')]['candidate']=='UNKNOWN' and ledger[selection][(code,'b')]['candidate']=='UNKNOWN';continue
   n=dd.index(signal)+1;hist=dd[:n];rr={f:arrays[f][:n] for f in fields};ee=[e for e in events if e['date']<=signal];q=adjusted(hist,rr,ee,signal);identity=canon({'code':code,'dates':hist,'events':ee,'raw':{f:rr[f].tolist() for f in fields},'adjusted':{f:q[f].tolist() for f in fields}})
   assert identity==ledger[selection][(code,'a')]['dated_input_sha256']==ledger[selection][(code,'b')]['dated_input_sha256']
   try:
    if any(hist[0]<event<=signal for event in unsupported):raise ValueError('UNSUPPORTED_SPLIT_EVENT')
    actual=a.evaluate(program,{name:q[f] for name,f in [('O','open'),('H','high'),('L','low'),('C','close'),('VOL','volume'),('AMOUNT','amount')]},code);last={name:float(v[-1]) if np.isfinite(v[-1]) else None for name,v in actual.items()};assert last==avalues[selection][code]
   except (a.FormulaError,ValueError):assert ledger[selection][(code,'a')]['candidate']=='UNKNOWN' and avalues[selection][code]=={}
   calc=k.evaluate_stock(code,hist,{name:q[f] for name,f in [('C','close'),('H','high'),('L','low'),('VOL','volume')]},signal_date=signal)
   assert calc['candidate']==ledger[selection][(code,'b')]['candidate'] and '|'.join(calc['hit_rules'])==ledger[selection][(code,'b')]['hit_rules'] and '|'.join(calc['unknown_rules'])==ledger[selection][(code,'b')]['unknown_rules']
   for rule in calc['rules']:assert rule['status']==rulemap[selection][(code,rule['rule_id'])]['status']
   # Future event injection must be ignored; a future RAW row with an earlier anchor must reject.
   future=dict(date='20990101',A=0.001,B=-9999.,G=1000.);check=writer_engine.project(hist,rr,ee+[future],signal)
   assert all(np.array_equal(check[f],q[f],equal_nan=True) for f in fields);negative_checks+=1
   try:writer_engine.project(hist+['20990101'],{f:np.append(rr[f],rr[f][-1]) for f in fields},ee,signal)
   except AssertionError:negative_checks+=1
   else:raise AssertionError('FUTURE_RAW_ROW_NOT_REJECTED')
   replays+=1
  sample_bindings.append(dict(code=code,rows=len(dd),raw_binding=canon({'dates':dd,'raw':{f:v.tolist() for f,v in arrays.items()}})))
 # Full benchmark independently decodes only relevant native dates; no model reruns.
 expected={selection:[] for _,selection in dates[:5]};excluded=Counter()
 for code in codes:
  spec=specs[code]
  if code not in m['catalog']:
   for _,selection in dates[:5]:excluded[(selection,'SOURCE_UNKNOWN')]+=1
   continue
  raw=direct_raw(code,spec);events,unsupported=ev(spec)
  for signal,selection in dates[:5]:
   if selection not in raw:excluded[(selection,'EXACT_TARGET_BAR_MISSING_NO_DATE_SUBSTITUTION')]+=1;continue
   if signal not in raw:excluded[(selection,'EXACT_PREVIOUS_MARKET_SESSION_BAR_MISSING_OR_IPO')]+=1;continue
   if sorted(raw).index(selection)!=sorted(raw).index(signal)+1:excluded[(selection,'PREVIOUS_MARKET_SESSION_KEY_MISMATCH')]+=1;continue
   if raw[selection]['volume']<=0:excluded[(selection,'ZERO_RAW_VOLUME_NO_TRADED_TARGET')]+=1;continue
   if any(signal<e<=selection for e in unsupported):excluded[(selection,'UNSUPPORTED_SPLIT_EVENT_IN_REFERENCE_INTERVAL')]+=1;continue
   reference=raw[signal]['close']
   for event in events:
    if signal<event['date']<=selection:reference=reference*event['A']+event['B']
   if reference<=0:excluded[(selection,'REFERENCE_PRICE_INVALID')]+=1;continue
   pct=(raw[selection]['close']/reference-1)*100;expected[selection].append((code,pct))
 summaries={r['selection_date']:r for r in csvrows(d/'comparison/DAILY_SUMMARY.csv')};actual_ex=Counter((r['selection_date'],r['reason']) for r in csvrows(d/'benchmarks/BENCHMARK_EXCLUSIONS.csv') if r['selection_date']!='20261023');assert actual_ex==excluded
 alljoin=[];category_counts=Counter()
 for signal,selection in dates[:5]:
  rank=sorted(expected[selection],key=lambda r:(-r[1],r[0]));full=csvrows(d/'benchmarks'/(selection+'_ELIGIBLE_RESEARCH_RANKING.csv'));assert [r['code'] for r in full]==[r[0] for r in rank] and len({r['code'] for r in full})==len(full)
  assert all(float(r['pct_change'])==v for r,(_,v) in zip(full,rank));top=csvrows(d/'benchmarks'/(selection+'_TOP100.csv'));assert top==full[:100] and len(top)==100
  joined=csvrows(d/'comparison'/(selection+'_TOP100_COMPARISON.csv'));assert [r['code'] for r in joined]==[r['code'] for r in top];cats=Counter();ca=Counter();cb=Counter()
  for row in joined:
   sa=ledger[selection][(row['code'],'a')]['candidate'];sb=ledger[selection][(row['code'],'b')]['candidate'];category='UNKNOWN_IMPACT' if 'UNKNOWN' in [sa,sb] else 'COMMON_HIT' if sa==sb=='YES' else 'A_EXCLUSIVE_HIT' if sa=='YES' else 'B_EXCLUSIVE_HIT' if sb=='YES' else 'COMMON_MISS_CONFIRMED';assert row['model_a']==sa and row['model_b']==sb and row['comparison_category']==category;cats[category]+=1;ca[sa]+=1;cb[sb]+=1
  summary=summaries[selection];assert int(summary['model_a_top100_yes'])==ca['YES'] and int(summary['model_b_top100_yes'])==cb['YES'] and int(summary['unknown_impact'])==cats['UNKNOWN_IMPACT'];assert int(summary['benchmark_eligible'])==len(full)
  alljoin.extend(joined);category_counts.update(cats)
 assert len(alljoin)==500 and alljoin==csvrows(d/'comparison/TOP100_COMPARISON_500.csv')
 for category in ['COMMON_HIT','A_EXCLUSIVE_HIT','B_EXCLUSIVE_HIT','COMMON_MISS_CONFIRMED','UNKNOWN_IMPACT']:assert csvrows(d/'comparison'/(category+'.csv'))==[r for r in alljoin if r['comparison_category']==category]
 snapshot=load(b['pointer_snapshot']);maximum=max(r['footer']['trade_date_max_metadata'] for r in snapshot['pointer_observations']);assert maximum=='20261022' and summaries['20261023']['benchmark_status']=='CANNOT_CONFIRM' and summaries['20261023']['benchmark_reason']=='NO_D23_BENCHMARK'
 result=dict(verdict='PASS_SCOPED_RESEARCH_COMPARISON_WITH_EXPLICIT_LIMITATIONS',started_at=started,finished_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-t,full_ledger_rows=11066*6,full_code_dates=5533*6,sample_source_codes=len(sample_codes),sample_model_code_dates=replays,cutoff_negative_cases=negative_checks,D23_reused_code_count=5533,main_top100_rows=500,category_counts=dict(category_counts),compact_rule_expansion=expanded_missing,compact_rule_causes=missing_rule_causes,actual_002388_missing_bar_regression=True,compact_unknown_negative_cases=regression_negative_cases,samples=sample_bindings,limits=['Research pool not certified historical all-A universe; historical PIT/qualification and global cross-vendor O/amount/volume units CANNOT_CONFIRM','D23 benchmark CANNOT_CONFIRM:NO_D23_BENCHMARK','B rule longtables omit unavailable sources and unavailable exact dated signal bars; only proven explicit all10-rule UNKNOWN records restore coverage','Openbook descriptive comparison; static diagnostic manifest price exposure admitted; no blind/sealed-forecast claim','V1927 is repaired event-affine input replay; old RAW5494 result5 is different basis and not explained by a single cause'],research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 with (out/'INDEPENDENT_VERIFIER_RECEIPT.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ['samples','limits']},ensure_ascii=False));return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
