"""Independent-review command: source arrays, event arithmetic, new evaluations and final accounting."""
import argparse,ast,csv,gzip,hashlib,importlib.util,json,math,os,sys,zipfile
from pathlib import Path
from collections import Counter
sys.dont_write_bytecode=True
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def j(p):return json.loads(Path(p).read_text())
def csvrows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def canon(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def stat(p):
 s=Path(p).stat();return {'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'size_bytes':s.st_size}
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=j(cp);assert Path(sys.executable).resolve()==Path(c['runtime']['python_executable']).resolve(),'REVIEW_RUNTIME_DRIFT';b=c['input_identity'];out=Path(c['output_directory']);writes=[]
 def fence(event,args):
  if event.startswith(('socket.connect','socket.bind','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_REVIEW_ONLY')
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
   p=Path(os.fsdecode(args[0])).resolve();assert out.resolve() in p.parents,'REVIEW_WRITE_BOUNDARY';writes.append(str(p))
 sys.addaudithook(fence);import numpy as np,pyarrow.dataset as ds,pyarrow.parquet as pq
 kernel=module(b['kernel'],'review_same_kernel');source60=j(b['contract60']);source63=j(b['contract63']);source64=j(b['contract64']);source65=j(b['contract65']);manifest=j(b['input_manifest']);result=j(Path(b['selection'])/'RESULT_RECEIPT.json');catalog=manifest['catalog'];statuses={r['code']:r for r in manifest['all_input_statuses']};target=j(source60['input_identity']['target_list'])['targets'];universe=csvrows(source60['input_identity']['universe']);current={r['ts_code'] for r in universe if r['trade_date']=='20261022'};assert len(universe)==5812 and len(current)==5494 and len(target)==len(statuses)==5533 and set(statuses)=={r['code'] for r in target};assert len(catalog)==5531 and set(statuses)-set(catalog)=={'301139.SZ','603007.SH'}
 matrix=csvrows(source60['input_identity']['matrix']);assert len(matrix)==318 and Counter(r['instrument_type'] for r in matrix)=={'EQUITY':302,'EQUITY_STOCK':4,'BOND':9,'INDEX':2,'UNKNOWN':1};assert set(source60['instrument_type_partition'])=={r['instrument_type'] for r in matrix};assert '920003.BJ' in statuses
 panel=source60['input_identity']['raw_selector'];archive=source60['input_identity']['archive'];assert stat(panel['path'])==panel['stat'] and stat(archive['path'])==archive['stat'];cols=['ts_code','trade_date','open','high','low','close','volume'];frame=ds.dataset(panel['path'],format='parquet').scanner(columns=cols,filter=ds.field('ts_code').isin(sorted(current))&(ds.field('trade_date')<='20261022'),use_threads=False,batch_size=65536).to_table().to_pandas();assert not frame.duplicated(['ts_code','trade_date']).any();groups=frame.groupby('ts_code',sort=False);native=j(source60['input_identity']['native_refs']);events=j(source60['input_identity']['event_refs']);r63=j(Path(source63['output_directory'])/'PREFIX_REPAIR_RECEIPT.json');repaired63={r['code'] for r in r63['records'] if r['status']=='READY'};repaired64={r['code'] for r in manifest['final64_records'] if r['status']=='READY'};reuse57=source60['input_identity']['reuse_verified_inputs'];zero_counts=Counter();checked_rows=0;reconstructed=0;sample_inputs={};selectedrows={}
 for line in (Path(b['selection'])/'ALL_CANONICAL_RESULTS.jsonl').open(encoding='utf-8'):
  r=json.loads(line);assert r['code'] not in selectedrows;selectedrows[r['code']]=r
 assert set(selectedrows)==set(statuses);old_samples=sorted(r['code'] for r in selectedrows.values() if r['candidate']=='YES' and r['evaluation_provenance']['kind'].startswith('REUSED'))[:5]+sorted(r['code'] for r in selectedrows.values() if r['candidate']=='NO' and r['evaluation_provenance']['kind'].startswith('REUSED'))[:5]
 dtype=np.dtype([('date','<u4'),('open','<u4'),('high','<u4'),('low','<u4'),('close','<u4'),('amount','<f4'),('volume','<u4'),('reserved','<u4')]);fields=['open','high','low','close','volume'];boundary_calendar=None;member_cache={}
 with zipfile.ZipFile(archive['path']) as z:
  members={p.filename.replace('\\','/').lower():p for p in z.infolist()}
  def arc(code):
   num,ex=code.split('.');p=members[ex.lower()+'/lday/'+ex.lower()+num+'.day'];payload=z.read(p);assert len(payload)%32==0;a=np.frombuffer(payload,dtype=dtype);dates=a['date'].astype('U8');assert list(dates)==sorted(set(dates));return a[dates<='20261022'],hashlib.sha256(payload).hexdigest()
  for cal in manifest['final64_calendar_bindings']:
   p=next(x for x in members.values() if x.filename==cal['member']);payload=z.read(p);assert hashlib.sha256(payload).hexdigest()==cal['sha256'];dates=np.frombuffer(payload,dtype=dtype)['date'].astype('U8');d=[x for x in dates if '20240801'<=x<='20261022'];assert boundary_calendar is None or d==boundary_calendar;boundary_calendar=d
  for code,spec in sorted(catalog.items()):
   assert sha(spec['path'])==spec['sha256'];data=csvrows(spec['path']) if spec['format']=='csv' else pq.read_table(spec['path']).to_pylist();dates=[str(r['trade_date']) for r in data];assert len(data)==spec['rows'] and dates==sorted(set(dates)) and dates[0]==spec['first_date'] and dates[-1]==spec['last_date']=='20261022' and all(r['ts_code']==code for r in data);actual={f:np.asarray([float(r[f]) if r[f] is not None else np.nan for r in data]) for f in fields};assert sha(events[code]['path'])==events[code]['sha256'];capture=j(events[code]['path']);assert capture['response_error'] is None and isinstance(capture['response_rows'],list);ev=[]
   for e in capture['response_rows']:
    d=int(e['year'])*10000+int(e['month'])*100+int(e['day'])
    if d>20261022 or e['category']!=1:continue
    cash,rightsprice,bonus,rights=[e[k] for k in ['fenhong','peigujia','songzhuangu','peigu']];assert all(isinstance(x,(int,float)) and math.isfinite(x) for x in [cash,rightsprice,bonus,rights]);g=1+bonus/10+rights/10;assert g>0;ev.append({'date':d,'A':1/g,'B':(-cash/10+rightsprice*rights/10)/g,'share_multiplier':g})
   ev.sort(key=lambda e:e['date']);assert len({e['date'] for e in ev})==len(ev)
   if code in reuse57:
    assert spec['sha256']==reuse57[code]['sha256'] and canon(ev)==reuse57[code]['event_semantics_sha256'];reconstructed+=1
   else:
    if code in current and code not in repaired64:
     old=groups.get_group(code).sort_values('trade_date');raw={str(r['trade_date']):{f:float(r[f]) if r[f] is not None else np.nan for f in fields} for r in old.to_dict('records')}
     if code in repaired63:
      a,h=arc(code);ds0=a['date'].astype('U8')
      for i,d in enumerate(ds0):
       if d in raw:raw[d]={f:float(a[f][i])/(100 if f!='volume' else 1) for f in fields}
     ref=native[code];assert sha(ref['path'])==ref['sha256'];payload=Path(ref['path']).read_bytes();assert len(payload)%32==0;a=np.frombuffer(payload,dtype=dtype);d0=a['date'].astype('U8');assert list(d0)==sorted(set(d0)) and d0[-1]=='20261022'
     for i,d in enumerate(d0):
      assert d<='20261022'
      if d in raw and raw[d]['volume']==0 and a['volume'][i]>0:zero_counts[d]+=1
      raw[d]={f:float(a[f][i])/(100 if f!='volume' else 1) for f in fields}
     assert set(old['trade_date']).issubset(raw)
    else:
     a,h=arc(code);d0=a['date'].astype('U8');lo=spec.get('compute_window_start','00000000') if code in repaired64 else '00000000';raw={d:{f:float(a[f][i])/(100 if f!='volume' else 1) for f in fields} for i,d in enumerate(d0) if d>=lo}
    assert sorted(raw)==dates,'SOURCE_DATE_OR_KEY_MISMATCH:'+code;da=np.asarray(dates,dtype=np.int64);A=np.ones(len(data));B=np.zeros(len(data));G=np.ones(len(data))
    for e in ev:
     mask=da<e['date'];A[mask]*=e['A'];B[mask]=B[mask]*e['A']+e['B'];G[mask]*=e['share_multiplier']
    for f in fields:
     v=np.asarray([raw[d][f] for d in dates]);expect=v*G if f=='volume' else v*A+B;assert np.array_equal(expect,actual[f],equal_nan=True),'EXACT_SOURCE_AFFINE_OR_VOLUME_MISMATCH:'+code+':'+f
    reconstructed+=1
   checked_rows+=len(data);row=selectedrows[code];assert row['input_source_sha256']==spec['sha256'] and row['input_row_sha256']==spec['row_sha256']
   if row['evaluation_provenance']['kind'].startswith('EVALUATED') or code in old_samples:sample_inputs[code]=(dates,actual)
 # The original source-zero count uses native-before repair, not the reconstructed post-archive prefix.
 assert reconstructed==5531
 original_zero_counts=Counter()
 for code in sorted(current):
  ref=native[code];payload=Path(ref['path']).read_bytes();assert hashlib.sha256(payload).hexdigest()==ref['sha256'];a=np.frombuffer(payload,dtype=dtype);dates=a['date'].astype('U8');oldvol=groups.get_group(code).set_index('trade_date')['volume'].reindex(dates).to_numpy();mask=(oldvol==0)&(a['volume']>0)
  original_zero_counts.update(dates[mask].tolist())
 assert dict(original_zero_counts)==j(Path(source60['output_directory'])/'INPUT_MANIFEST.json')['selector_zero_native_positive_by_date'],'SHARED_ZERO_PROJECTION_COUNT_MISMATCH'
 # Exact production dated-event loop: positive plus outside-window/missing-binding/wrong-listing fail closed.
 tree=ast.parse(Path(b['market_event_code']).read_text());loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='error' and ast.unparse(n.iter)=="v['failures']");code_loop=compile(ast.Module(body=[loop],type_ignores=[]),b['market_event_code'],'exec');boundary=0
 for record in manifest['final64_records']:
  for positive in record.get('exact_legal_exceptions',[]):
   legal=positive['exact_legal_rule'];error=positive['original_failure'];first=legal.get('listing_date');alldates=[first] if first else ['20240101'];baseenv={'v':{'failures':[error]},'legal':legal,'market_dates':boundary_calendar,'alldates':alldates,'allowed':[],'remaining':[]};exec(code_loop,baseenv);assert len(baseenv['allowed'])==1;boundary+=1
   none={**baseenv,'legal':None,'allowed':[],'remaining':[]};exec(code_loop,none);assert not none['allowed'] and len(none['remaining'])==1;boundary+=1
   if first:
    six=[d for d in boundary_calendar if d>=first][:6];late={**error,'date':int(six[5]),'previous_date':int(six[4])};env={**baseenv,'v':{'failures':[late]},'allowed':[],'remaining':[]};exec(code_loop,env);assert not env['allowed'];boundary+=1
    env={**baseenv,'alldates':['19000101'],'allowed':[],'remaining':[]};exec(code_loop,env);assert not env['allowed'];boundary+=1
   for field in ['source_text_path','source_text_sha256']:
    assert legal[field] and source64['frozen_source_bindings'][legal['source_text_path']]==legal['source_text_sha256'] and sha(legal['source_text_path'])==legal['source_text_sha256']
 sys.path.insert(0,source60['input_identity']['owner_worktree']);from ops import a_share_daily_sync as owner
 badbar={'year':2026,'month':10,'day':22,'open':1.,'high':1.,'low':1.,'close':float('nan'),'amount':1.,'vol':1.};assert not owner.valid_hq_bar(badbar)[0];boundary+=1
 for e in manifest['final64_inherited63_IPO_calendar_rechecked']:
  five=[d for d in boundary_calendar if d>=e['listing_date']][:5];assert five==e['exact_first_five_market_dates'] and e['date'] in five
 # New inputs are evaluated independently; identical old-source rows have a bounded reader sample only.
 replays=0
 for code,(dates,data) in sample_inputs.items():
  calc=kernel.evaluate_stock(code,dates,{k:data[v] for k,v in [('C','close'),('H','high'),('L','low'),('VOL','volume')]});actual=selectedrows[code];assert all(calc[k]==actual[k] for k in calc),'SIGNAL_REPLAY_MISMATCH:'+code;replays+=1
 counts=Counter();provenance=Counter();hitcodes=[];partrows={}
 for part in result['parts']:
  assert sha(part['path'])==part['sha256'];pr=[json.loads(x) for x in Path(part['path']).read_text().splitlines()];assert len(pr)==part['rows']
  for r in pr:assert r['code'] not in partrows;partrows[r['code']]=r
 assert partrows==selectedrows
 for code,r in selectedrows.items():
  assert r['signal_date']=='20261022';assert len(r['rules'])==len({x['rule_id'] for x in r['rules']})==10;hits=[x['rule_id'] for x in r['rules'] if x['value'] is True];unknown=[x['rule_id'] for x in r['rules'] if x['value'] is None];assert hits==r['hit_rules'] and unknown==r['unknown_rules'];assert r['candidate']==('YES' if hits else 'UNKNOWN' if unknown else 'NO');counts[r['candidate']]+=1;provenance[r['evaluation_provenance']['kind']]+=1
  if r['candidate']=='YES':hitcodes.append(code)
  if code not in catalog:assert r['candidate']=='UNKNOWN' and len(unknown)==10
 assert counts==result['candidate_counts'] and provenance==result['evaluation_provenance_counts'];union=csvrows(Path(b['selection'])/'UNION_CANDIDATES.csv');assert [r['code'] for r in union]==sorted(hitcodes) and len(union)==204
 for r in union:assert r['hit_rules']=='|'.join(selectedrows[r['code']]['hit_rules']) and r['unknown_rules']=='|'.join(selectedrows[r['code']]['unknown_rules'])
 for rid in kernel.RULES:
  entries=csvrows(Path(b['selection'])/(rid+'_CANDIDATES.csv'));assert [r['code'] for r in entries]==[r['code'] for r in union if rid in r['hit_rules'].split('|')]
 long=csvrows(Path(b['selection'])/'TEN_ROUTE_LONG.csv');assert len(long)==55330 and len({(r['code'],r['rule_id']) for r in long})==55330
 for r in long:assert r['status']==next(x['status'] for x in selectedrows[r['code']]['rules'] if x['rule_id']==r['rule_id']) and r['candidate']==selectedrows[r['code']]['candidate']
 for r in csvrows(Path(b['selection'])/'RULE_COVERAGE.csv'):
  counts0=Counter(next(x['status'] for x in s['rules'] if x['rule_id']==r['rule_id']) for s in selectedrows.values());assert all(int(r[k])==counts0[k] for k in ['TRIGGERED','NOT_TRIGGERED','DATA_UNAVAILABLE'])
 lineage=j(b['disposition318']);slice318=csvrows(Path(b['selection'])/'ORIGINAL318_SAME_RUN_SLICE.csv');assert len(lineage)==len(slice318)==318 and [r['source_key'] for r in lineage]==[r['source_key'] for r in slice318];assert Counter(r['disposition'] for r in lineage)==result['original318_disposition_counts']
 for r in slice318:
  got=selectedrows.get(r['canonical_code']);assert r['candidate']==(got['candidate'] if got else 'NOT_EVALUATED_DISPOSITION') and r['hit_rules']==('|'.join(got['hit_rules']) if got else '')
 delivery=j(Path(b['delivery'])/'DELIVERY_RECEIPT.json')
 for p,h in delivery['files'].items():
  assert sha(p)==h;annot=csvrows(p);original=csvrows(Path(b['selection'])/Path(p).name);assert len(annot)==len(original)
  for a,o in zip(annot,original):assert {k:v for k,v in a.items() if k!='name'}=={k:v for k,v in o.items() if k!='name'}
 for u in delivery['updated_names']:
  assert {e['name'] for e in u['evidence']}=={u['name']}
  for e in u['evidence']:assert sha(e['source']['path'])==e['source']['sha256']
 assert stat(panel['path'])==panel['stat'] and stat(archive['path'])==archive['stat']
 for p,h in c['frozen_source_bindings'].items():assert sha(p)==h
 receipt={'status':'READY_INDEPENDENT_REVIEWER_MUST_ASSESS_SCOPE','execution_id':c['execution_id'],'source_inputs_reconstructed_or_prior57_reused':reconstructed,'input_rows_checked':checked_rows,'original_selector_zero_native_positive_by_date':dict(original_zero_counts),'new_and_reader_sample_signal_replays':replays,'calendar_and_market_boundary_cases':boundary,'logical_result_rows':5533,'long_rows':55330,'candidate_counts':dict(counts),'provenance_counts':dict(provenance),'original318_rows':318,'unique_candidates':204,'original318_hit_source_keys':9,'source_unavailable':['301139.SZ','603007.SH'],'name_unknown':['920066.BJ','920176.BJ'],'network':0,'native_writes':0,'historical_PIT_and_live_platform_parity':'NOT_CERTIFIED','current_UI_API':'NOT_VERIFIED','research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};Path(out/'VERIFICATION_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False));return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
