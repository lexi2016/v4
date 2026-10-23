"""Frozen 387-event descriptive diagnostics. Never edits a producer or model."""
from __future__ import annotations
import os,sys,json,csv,time,math,resource,argparse,multiprocessing,re
from pathlib import Path
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.dont_write_bytecode=True
from registry_bridge import w,register,ROOT,OLD
from reference import Reference,render,atoms,scalar
sys.path.insert(0,str(OLD));import engine as e
OUT=ROOT/'research/week_miss387_diagnosis_20261023'
HERE=Path(__file__).resolve().parent
PRIOR=ROOT/'research/week_two_model_comparison_20261023'
CP=OUT/'DIAGNOSIS_CONTRACT_R2.json'
DATES=[('20261015','20261016'),('20261016','20261019'),('20261019','20261020'),('20261020','20261021'),('20261021','20261022')]
AKEYS=['ENTRYPOOL','BRICKPOOL','PRIMARY','SECONDARY','B1SIG','B2SIG','B3SIG','BKEXIST','BKRES','BKBUY','DBREAK','XSTAR','FRESH','CONT0','FCON','CCON','RISK0','RISKCAP','RISKPN','HOTFAR','LATEFLAG','WEAKFLAG','DISTFLAG','MULTI','STABLE','VOLSTB','B2ROLE','B3ROLE','XG']
def readcsv(p):
 with Path(p).open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def clean(x):
 if isinstance(x,np.ndarray):return [clean(v) for v in x.tolist()]
 if isinstance(x,(np.floating,float)):return float(x) if np.isfinite(x) else None
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 if isinstance(x,np.integer):return int(x)
 if isinstance(x,np.bool_):return bool(x)
 return x
def save(p,x):w.save(p,clean(x))
def same(x,y):
 if x is None or y is None:return x is None and y is None
 return bool(np.isclose(x,y,rtol=1e-10,atol=1e-8))
def status(x):return 'UNKNOWN' if x is None else 'YES' if x!=0 else 'NO'
def stat0(p):
 z=Path(p).stat();return dict(inode=z.st_ino,size_bytes=z.st_size,mtime_ns=z.st_mtime_ns)
def prepare():
 c=w.load(PRIOR/'EXECUTION_CONTRACT.json');paths=[HERE/'diagnose.py',HERE/'reference.py',HERE/'registry_bridge.py',PRIOR/'comparison/COMMON_MISS_CONFIRMED.csv',PRIOR/'comparison/DAILY_SUMMARY.csv',PRIOR/'FINAL_ACCEPTANCE.json',PRIOR/'EXECUTION_CONTRACT.json',PRIOR/'REVIEW_R2_CONTRACT.json',PRIOR/'SOURCE_IDENTITY_SUPPLEMENT.json',PRIOR/'SIGNALS_SEALED.json',OLD/'engine.py',OLD/'weekly_compare.py']
 frozen={**c['frozen_source_bindings'],**{str(p):w.sha(p) for p in paths}}
 seal=w.load(PRIOR/'SIGNALS_SEALED.json');frozen.update({str(PRIOR/p):h for p,h in seal['files'].items()})
 identity=dict(prior_contract_sha256=w.sha(PRIOR/'EXECUTION_CONTRACT.json'),miss_list_path=str(paths[3]),miss_list_sha256=frozen[str(paths[3])],frozen_source_binding_digest=w.digest(frozen),source_input_identity=c['input_identity'])
 contract=dict(schema='MISS387_TECHNICAL_DIAGNOSIS_V1',GOAL='Explain exactly the accepted 387 common-miss code/date events using unchanged frozen formulas and original dated inputs',WRITER='/root/miss387_writer',REVIEWER='/root/miss387_review',ALLOWED_PATHS=[str(HERE),str(OUT),'append-only official registry and minimal current registry summaries'],FORBIDDEN_PATHS=[str(OUT/'catalyst'),str(OUT/'independent_review'),'original sources/formulas/old comparison','V3/V4/services/schedules/Windows/SSH/trading'],PASS_SIGNAL='387 unique rows; exact date map; original ledger parity or explicit counterexample; atomic false conditions with terminal values; independent scoped Reviewer PASS',STOP_RULE='Stop and report input/implementation discrepancies; no silent source/model changes; bounded repairs only diagnostic code; no threshold optimization',route_id='A_SHARE_WEEK_MISS387_DIAGNOSIS_20261023',execution_id='A_SHARE_WEEK_MISS387_DIAGNOSIS_20261023_02',track_id='A_SHARE_OPENBOOK_COMMON_MISS_DIAGNOSIS',baseline_id=c['baseline_id'],one_variable='EXPLANATION_AND_INDEPENDENT_NUMERICAL_INTERPRETER_ONLY_UNCHANGED_MODELS',signal_date_range=['20261015','20261021'],target_date_range=['20261016','20261022'],truth_access='OPENBOOK_COMMON_MISS_AND_PRICE_ALREADY_EXPOSED',sealed_status='OPENBOOK_DESCRIPTIVE_NOT_BREAKTHROUGH',runtime={'python_executable':w.PYTHON,'workers_canary':2,'workers_full':4,'worker_max':4},device='MAC_LOCAL_CPU',input_identity=identity,input_sha256=w.digest(identity),code_sha256=w.digest({str(p):w.sha(p) for p in [HERE/'diagnose.py',HERE/'reference.py',HERE/'registry_bridge.py']}),frozen_source_bindings=frozen,expected_daily_counts={'20261016':92,'20261019':76,'20261020':64,'20261021':65,'20261022':90},expected_unique_keys=387,date_pairs=DATES,primary_reason_rule='DATA_INVALID_OR_UNKNOWN first; then IMPLEMENTATION_OR_ARCHIVE_PARITY_DIFFERENCE; else ENTRYPOOL_FALSE; else RISK0_GE45; else ROLE_SCORE_OR_ROUTE_FALSE; then UNCLASSIFIED_FLAG',multi_label_rule='All actual false terminal A gates and B route leaves retained; unknown historical certification is a separate evidence axis, not asserted causal failure',reference_scope='All255 A terminal values and all reachable B numerical assignments plus BRICK independent recurrence; shared immutable parser AST; independently coded NumPy rolling/scalar recurrence; not TDX/Futu engine parity',comparison_tolerance={'rtol':1e-10,'atol':1e-8,'boolean_and_candidate':'EXACT'},warmup_policy='Record observed history and finite counts; >=200 bars covers fixed windows but not infinite EMA seed/platform equivalence',prior_full_audit='REUSE_EXISTING_PASS_FAST_BIND_NO_5533_RERUN',limitations=['CURRENT_SOURCE_POOL_NOT_CERTIFIED_HISTORICAL_ALL_A','SOURCE_AVAILABLE_AT_AND_HISTORICAL_VINTAGE_CANNOT_CONFIRM','CROSS_VENDOR_VOLUME_AMOUNT_UNIT_PARITY_CANNOT_CONFIRM','PLATFORM_TDX_FUTU_ORIGINAL_ENGINE_PARITY_CANNOT_CONFIRM'],**w.FLAGS)
 save(CP,contract);register(CP,'RUN_STARTED','TECH_R2_START',decision='RUNNING_FAST_BIND_THEN_CANARY');print(str(CP),flush=True)

def independent_brick(raw):
 def rec(x,n):
  last=None;out=[]
  for y in x:last=y if last is None else y/n+(1-1/n)*last;out.append(last)
  return out
 def val(offset):
  n=len(raw['C'])-offset
  if n<12:return 0.0
  h,l,c=[raw[k][:n] for k in ['H','L','C']];u=[];v=[]
  for i in range(3,n):
   top=max(h[i-3:i+1]);bottom=min(l[i-3:i+1]);span=top-bottom
   u.append(50.0 if span==0 else (c[i]-bottom)/span*100);v.append(-90.0 if span==0 else (top-c[i])/span*100-90)
  br=rec(rec(u,6),6)[-1]-rec(v,4)[-1]
  return round(max(br-4,0),2)
 b,y,t=[val(i) for i in [2,1,0]]
 return dict(brick_before=b,brick_yesterday=y,brick_today=t,threshold=y+(b-y)*2/3,atoms=[dict(expression='brick_today > brick_yesterday',lhs=t,rhs=y,value=float(t>y)),dict(expression='brick_yesterday < brick_before',lhs=y,rhs=b,value=float(y<b)),dict(expression='brick_today > threshold',lhs=t,rhs=y+(b-y)*2/3,value=float(t>y+(b-y)*2/3))])
def eval_at(code,dates,raw,ev,cutoff,a,program,k,do_reference):
 n=dates.index(cutoff)+1;d=dates[:n];r={f:raw[f][:n] for f in e.FIELDS};events=[v for v in ev if v['date']<=cutoff];q=e.project(d,r,events,cutoff)
 identity=w.digest({'code':code,'dates':d,'events':events,'raw':{f:r[f].tolist() for f in e.FIELDS},'adjusted':{f:q[f].tolist() for f in e.FIELDS}})
 ra={x:q[y] for x,y in [('O','open'),('H','high'),('L','low'),('C','close'),('VOL','volume'),('AMOUNT','amount')]};rb={x:ra[x] for x in ['C','H','L','VOL']}
 av=a.evaluate(program,ra,code);bv,be=k.evaluate_stock(code,d,rb,signal_date=cutoff,return_engine=True)
 result=dict(cutoff=cutoff,history_rows=n,input_sha256=identity,a_candidate=status(scalar(av['XG'])),b_candidate=bv['candidate'],a_key_values={x:scalar(av[x]) for x in AKEYS},b_hit_rules=bv['hit_rules'],b_unknown_rules=bv['unknown_rules'])
 if not do_reference:return result
 ar=Reference(program,ra,'A',code);br=Reference(be.nodes,be.raw,'B',code,be.reverse)
 # Materialize all255 and all reachable source assignments independently.
 aref={name:scalar(ar.named(name)) for name,_ in program};bref={name:scalar(br.named(name)) for name in be.nodes}
 aprod={name:scalar(value) for name,value in av.items()};bprod={name:scalar(be.named(name)) for name in be.nodes}
 adi=[dict(name=x,production=aprod[x],reference=aref[x]) for x in aref if not same(aprod[x],aref[x])];bdi=[dict(name=x,production=bprod[x],reference=bref[x]) for x in bref if not same(bprod[x],bref[x])]
 # Route explanations use production terminal arrays, keeping parser semantics
 # exact; independent atom checks compare their references separately above.
 ap=Reference(program,{**ra,**av},'A',code);bp=Reference(be.nodes,{**be.raw,**be.memo},'B',code,be.reverse)
 ast_a={name:dict(expression=render(node),value=aprod[name],dependencies=sorted(a.names_used(node)),atoms=atoms(node,ap,name)) for name,node in program}
 ast_b={name:dict(expression=render(node,be.reverse),value=bprod[name],dependencies=sorted(be.reverse.get(z,z) for z in a.names_used(node)),atoms=atoms(node,bp,name)) for name,node in be.nodes.items()}
 routes=[]
 for rule_id,name in k.RULES.items():
  rule=next(x for x in bv['rules'] if x['rule_id']==rule_id)
  if rule_id=='BRICK_FANBAO':
   brick=independent_brick(rb);brick_ref=bool(brick['atoms'][0]['value'] and brick['atoms'][1]['value'] and brick['atoms'][2]['value']);bdi.extend([] if brick_ref==rule['value'] else [dict(name='BRICK_FANBAO',production=rule['value'],reference=brick_ref)]);detail=dict(expression='today>yesterday AND yesterday<before AND today>yesterday+(before-yesterday)*2/3',value=rule['value'],atoms=brick['atoms'],production_evidence=rule['evidence'],independent_values=brick)
  else:detail=ast_b[name]
  routes.append(dict(rule_id=rule_id,source_name=name,status=rule['status'],**detail))
 result.update(a_all_terminal_values=aprod,a_assignments=ast_a,b_assignments=ast_b,b_rules=routes,reference=dict(a_terminal_count=len(aref),b_terminal_count=len(bref),a_differences=adi,b_differences=bdi,scope='SHARED_AST_INDEPENDENT_NUMERICS_NO_PLATFORM_CERTIFICATION'))
 return result

def diagnose_task(task):
 base,misses=task;code,spec,original,native,c56,b,_=base
 a=w.module(b['model_a'],'original_frozen_diag');program=a.compile_original(b['formula_a']);k=w.module(b['model_b'],'ten_frozen_diag')
 dates,raw,ev,unsupported,provenance=e.reconstruct(code,spec,original,native,c56)
 result=[]
 for miss in misses:
  signal=miss['signal_asof'];target=miss['selection_date'];n=dates.index(signal)+1
  p=eval_at(code,dates,raw,ev,signal,a,program,k,True)
  if any(dates[0]<u<=signal for u in unsupported):raise AssertionError('UNSUPPORTED_SPLIT_EVENT:'+code)
  later=eval_at(code,dates,raw,ev,target,a,program,k,False) if target in dates else dict(cutoff=target,status='EXACT_TARGET_BAR_MISSING')
  raw0={f:raw[f][:n] for f in e.FIELDS};q=e.project(dates[:n],raw0,[v for v in ev if v['date']<=signal],signal)
  fields={f:dict(raw_terminal=float(raw0[f][-1]),adjusted_terminal=float(q[f][-1]),raw_nonfinite_count=int((~np.isfinite(raw0[f])).sum()),adjusted_nonfinite_count=int((~np.isfinite(q[f])).sum()),zero_count=int((raw0[f]==0).sum()),native_unit='CNY_RETAINED' if f=='amount' else 'NATIVE_COUNT_ADJUSTED_BY_SHARE_RATIO' if f=='volume' else 'CNY_AFFINE_ADJUSTED') for f in e.FIELDS}
  issues=[]
  if not miss.get('name',spec.get('name','')):issues.append('NAME_MISSING')
  if n<200:issues.append('SHORT_HISTORY_LT200')
  if fields['volume']['raw_terminal']==0:issues.append('SIGNAL_ZERO_VOLUME')
  if any(v['adjusted_nonfinite_count'] for v in fields.values()):issues.append('ADJUSTED_PREFIX_NONFINITE')
  if len(original)!=len({str(x['trade_date']) for x in original}):issues.append('ORIGINAL_SELECTOR_DUPLICATE_DATES')
  audit=dict(input_status=spec['status'],source_branch='+'.join(v['role'] for v in provenance),sources=provenance,projection_path=spec['path'],projection_sha256=spec['sha256'],event_response_path=spec['event_response_path'],event_response_sha256=spec['event_response_sha256'],events_le_signal=[v for v in ev if v['date']<=signal],events_after_signal_excluded=[v['date'] for v in ev if v['date']>signal],raw_first_date=dates[0],raw_last_date=dates[-1],exact_signal_bar=dates[n-1],prefix_rows=n,duplicate_final_dates=len(dates)-len(set(dates)),original_selector_duplicate_dates=len(original)-len({str(x['trade_date']) for x in original}),fields=fields,issues=issues,missing_market_sessions='CANNOT_CONFIRM_NO_FROZEN_HISTORICAL_TRADING_CALENDAR',suspension='SIGNAL_ZERO_VOLUME' if fields['volume']['raw_terminal']==0 else 'SIGNAL_VOLUME_POSITIVE_HISTORY_ZERO_COUNTS_REPORTED',listing_date='CANNOT_CONFIRM_FIRST_OBSERVED_BAR_IS_NOT_LISTING_DATE',historical_code_identity='CURRENT_BOUND_CODE_ONLY_HISTORICAL_ALIAS_ELIGIBILITY_CANNOT_CONFIRM',name_status='MISSING' if not miss.get('name',spec.get('name','')) else 'PRESENT_NOT_CERTIFIED_HISTORICAL_ALIAS',warmup=dict(rows=n,fixed_window_max200_covered=n>=200,a_partial_window_policy=True,b_full_window_policy=True,ema_seed_history='FIRST_FINITE_OBSERVATION_NO_INFINITE_HISTORY_CERTIFICATION'),adjustment='PER_SIGNAL_AFFINE_EVENTS_LE_SIGNAL_UNROUNDED_PRICES_SHARE_VOLUME_AMOUNT_UNADJUSTED',price_clip='EXACT_BOUND_DATES_NO_IMPUTATION_NO_ROUNDING; FINAL_PREFIX_20261022; START_AS_SOURCE',historical_available_at='CANNOT_CONFIRM_SNAPSHOT_RETRIEVED20261023',cross_vendor_volume_amount_units='CANNOT_CONFIRM')
  result.append(dict(code=code,name=miss.get('name',spec.get('name','')),selection_date=target,signal_asof=signal,input_audit=audit,prior_row=miss,signal=p,target_day_posthoc=later))
 return dict(code=code,rows=result,worker_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

def validate_fastbind(c):
 old=w.load(PRIOR/'EXECUTION_CONTRACT.json')
 for name in ['raw_selector','archive']:
  b=old['input_identity'][name];assert stat0(b['path'])==b['stat'],'FAST_BIND_STAT_DRIFT:'+name
 for p,h in c['frozen_source_bindings'].items():assert w.sha(p)==h,'FROZEN_DRIFT:'+p
 return {'prior_static_full_sha_reused':True,'stat_bindings':{x:stat0(old['input_identity'][x]['path']) for x in ['raw_selector','archive']},'source_files_sha_unchanged':True}

def row_summary(row):
 p=row['signal'];a=p['a_key_values'];issues=row['input_audit']['issues'];diff=row['archive_parity'];refs=p['reference'];labels=[]
 for x in ['ENTRYPOOL','B2ROLE','B3ROLE','FCON','CCON']:
  if a[x]==0:labels.append('A_'+x+'_FALSE')
 for x,op,limit in [('RISK0','>=',45),('FRESH','<',70),('CONT0','<',70)]:
  if a[x] is not None and ((a[x]>=limit) if op=='>=' else (a[x]<limit)):labels.append('A_'+x+op+str(limit))
 labels.extend('B_'+x['rule_id']+'_FALSE' for x in p['b_rules'] if x['value'] is False or x['value']==0)
 labels.extend(issues)
 if issues and any(x in issues for x in ['ADJUSTED_PREFIX_NONFINITE','ORIGINAL_SELECTOR_DUPLICATE_DATES','SIGNAL_ZERO_VOLUME']):primary='DATA_INVALID_OR_UNKNOWN'
 elif not all(diff.values()) or refs['a_differences'] or refs['b_differences']:primary='IMPLEMENTATION_OR_ARCHIVE_PARITY_DIFFERENCE'
 elif a['ENTRYPOOL']==0:primary='ENTRYPOOL_FALSE'
 elif a['RISK0']>=45:primary='RISK0_GE45'
 elif not a['B2ROLE'] and not a['B3ROLE']:primary='ROLE_SCORE_OR_ROUTE_FALSE'
 else:primary='UNCLASSIFIED_FLAG'
 atext=f"A入口={a['ENTRYPOOL']:.0f}；B2ROLE={a['B2ROLE']:.0f}（风险{a['RISK0']:.3f}<45、鲜度{a['FRESH']:.3f}>=70、FCON={a['FCON']:.0f}）；B3ROLE={a['B3ROLE']:.0f}（续航{a['CONT0']:.3f}>=70、CCON={a['CCON']:.0f}）；最终XG={a['XG']:.0f}。"
 btexts=[]
 for r in p['b_rules']:
  failed=[x for x in r['atoms'] if x['value']==0]
  def atomtext(x):return x['expression']+('='+str(x['value']) if x['lhs'] is None else f"（左{x['lhs']!s}，右{x['rhs']!s}）")
  # Full AND/OR tree and every atom remain in JSONL; this view gives first3 false leaves.
  btexts.append(r['rule_id']+':'+('；'.join(atomtext(x) for x in failed[:3]) or '见依赖值与逻辑树'))
 late=row['target_day_posthoc'];return dict(selection_date=row['selection_date'],signal_asof=row['signal_asof'],code=row['code'],name=row['name'],primary_reason=primary,multi_labels='|'.join(labels),history_rows=p['history_rows'],source_branch=row['input_audit']['source_branch'],name_status=row['input_audit']['name_status'],input_local_issues='|'.join(issues),historical_PIT='CANNOT_CONFIRM',a_candidate=p['a_candidate'],b_candidate=p['b_candidate'],a_entrypool=a['ENTRYPOOL'],a_b2role=a['B2ROLE'],a_b3role=a['B3ROLE'],a_fresh=a['FRESH'],a_cont0=a['CONT0'],a_risk0=a['RISK0'],a_explanation_zh=atext,b_explanation_zh='；'.join(btexts),archive_parity=all(diff.values()),independent_reference_differences=len(refs['a_differences'])+len(refs['b_differences']),posthoc_D_a=late.get('a_candidate','UNKNOWN'),posthoc_D_b=late.get('b_candidate','UNKNOWN'),posthoc_D_b_hits='|'.join(late.get('b_hit_rules',[])),detail_reference='DETAILS.jsonl#'+row['selection_date']+'/'+row['code'])

def run(phase,workers):
 assert 2<=workers<=4;c=w.load(CP);start=time.monotonic();fb=validate_fastbind(c)
 rows=readcsv(PRIOR/'comparison/COMMON_MISS_CONFIRMED.csv');assert len(rows)==len({(x['selection_date'],x['code']) for x in rows})==387
 assert dict(Counter(x['selection_date'] for x in rows))==c['expected_daily_counts']
 assert all((x['signal_asof'],x['selection_date']) in DATES for x in rows)
 by=defaultdict(list)
 for x in rows:by[x['code']].append(x)
 old=w.load(PRIOR/'EXECUTION_CONTRACT.json');tasks=e.get_tasks(old,sorted(by))
 # Reduce carried56 metadata to a single code; reconstruction still reads the original frozen files.
 packed=[]
 for t in tasks:
  code,spec,orig,native,c56,b,reuse=t;cc=dict(c56);cc['input_identity']=dict(c56['input_identity']);cc['input_identity']['codes']={code:c56['input_identity']['codes'][code]} if code in c56['input_identity']['codes'] else {}
  packed.append(((code,spec,orig,native,cc,b,reuse),by[code]))
 if phase=='canary':
  selected={};
  for task in packed:
   spec=task[0][1];key='day' if spec.get('raw_path','').endswith('.day') else 'full' if spec.get('raw_full_history_path') else 'archive' if spec.get('archive_prefix_native_path') else 'selector'
   selected.setdefault(key,task)
  for task in packed:
   if task[0][0].endswith('.BJ') or len(task[0][2])<200:selected.setdefault('edge_'+task[0][0],task)
   if len(selected)>=8:break
  packed=list(selected.values())
 checkpoint=OUT/'checkpoints';checkpoint.mkdir(exist_ok=True);results=[]
 with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
  pending=[t for t in packed if not (checkpoint/(t[0][0]+'.json')).exists()]
  for i,res in enumerate(pool.map(diagnose_task,pending,chunksize=1)):
   save(checkpoint/(res['code']+'.json'),res)
   if phase=='full' and (i+1)%50==0:register(CP,'CHECKPOINT','TECH_FULL_'+str(i+1),[checkpoint/(res['code']+'.json')],{'processed_new_codes':i+1},'RUNNING_DIAGNOSTICS')
   if (i+1)%20==0:print(json.dumps({'phase':phase,'new_codes':i+1,'seconds':round(time.monotonic()-start,2)}),flush=True)
 for t in packed:results.extend(w.load(checkpoint/(t[0][0]+'.json'))['rows'])
 # Compare every recomputed D-1 A value/B rule/input identity to sealed old artifacts.
 archives={};barchives={};ledgers={}
 for signal,target in DATES:
  archives[target]={x['code']:x['values'] for x in map(json.loads,(PRIOR/'signals'/target/'MODEL_A_TERMINAL_VALUES.jsonl').read_text().splitlines())}
  barchives[target]={(x['code'],x['rule_id']):x for x in readcsv(PRIOR/'signals'/target/'MODEL_B_ALL_RULES.csv')}
  ledgers[target]={(x['code'],x['model']):x for x in readcsv(PRIOR/'signals'/target/'YES_NO_UNKNOWN.csv')}
 for row in results:
  code,target=row['code'],row['selection_date'];p=row['signal'];adiff=[dict(name=n,old=archives[target][code][n],new=v) for n,v in p['a_all_terminal_values'].items() if not same(v,archives[target][code][n])];bcheck=all(r['status']==barchives[target][(code,r['rule_id'])]['status'] for r in p['b_rules'])
  row['archive_a_differences']=adiff;row['archive_parity']=dict(a_all255=not adiff,b_all10_rule_status=bcheck,a_candidate=p['a_candidate']==ledgers[target][(code,'a')]['candidate'],b_candidate=p['b_candidate']==ledgers[target][(code,'b')]['candidate'],dated_input_sha256=p['input_sha256']==ledgers[target][(code,'a')]['dated_input_sha256'])
 summaries=[row_summary(r) for r in results];problems=[r for r in summaries if not r['archive_parity'] or r['independent_reference_differences'] or r['primary_reason'] in ['DATA_INVALID_OR_UNKNOWN','UNCLASSIFIED_FLAG']]
 summary=dict(phase=phase,code_count=len(packed),event_count=len(results),daily_counts=dict(Counter(r['selection_date'] for r in results)),primary_reason_counts=dict(Counter(r['primary_reason'] for r in summaries)),problem_count=len(problems),problem_keys=[{k:r[k] for k in ['selection_date','code','primary_reason','independent_reference_differences']} for r in problems],archive_parity_rows=sum(r['archive_parity'] for r in summaries),independent_reference_difference_rows=sum(bool(r['independent_reference_differences']) for r in summaries),fast_bind=fb,workers=workers,seconds=time.monotonic()-start,parent_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,status='ENGINEERING_CANARY_ONLY' if phase=='canary' else 'IMPLEMENTED_PENDING_INDEPENDENT_REVIEW',**w.FLAGS)
 if problems:save(OUT/(phase.upper()+'_PROBLEMS.json'),problems)
 if phase=='full':
  assert len(results)==387
  results.sort(key=lambda x:(x['selection_date'],x['code']));summaries.sort(key=lambda x:(x['selection_date'],x['code']))
  with (OUT/'DETAILS.jsonl').open('x') as f:
   for r in results:f.write(json.dumps(clean(r),ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
  w.csvwrite(OUT/'DIAGNOSIS_387.csv',summaries)
  for _,target in DATES:w.csvwrite(OUT/('DIAGNOSIS_'+target+'.csv'),[r for r in summaries if r['selection_date']==target])
  summary['posthoc_D_counts']=dict(a_yes=sum(r['posthoc_D_a']=='YES' for r in summaries),b_yes=sum(r['posthoc_D_b']=='YES' for r in summaries),note='POSTHOC_DIFFERENT_INFORMATION_TIME_NOT_PREDICTION')
  save(OUT/'SUMMARY.json',summary);save(OUT/'OUTPUT_MANIFEST.json',{str(p):w.sha(p) for p in [OUT/'DETAILS.jsonl',OUT/'DIAGNOSIS_387.csv',OUT/'SUMMARY.json',*[OUT/('DIAGNOSIS_'+t+'.csv') for _,t in DATES]]})
  register(CP,'TERMINAL','TECH_TERMINAL',[OUT/'SUMMARY.json',OUT/'OUTPUT_MANIFEST.json'],{'diagnosed_rows':len(results),'archive_parity_rows':summary['archive_parity_rows'],'independent_reference_difference_rows':summary['independent_reference_difference_rows']},'IMPLEMENTED_PENDING_INDEPENDENT_REVIEW' if not problems else 'CANNOT_CONFIRM_DIAGNOSTIC_DISCREPANCIES')
 else:save(OUT/'CANARY_SUMMARY.json',summary);register(CP,'CHECKPOINT','TECH_CANARY',[OUT/'CANARY_SUMMARY.json'],{'diagnosed_rows':len(results),'problems':len(problems)},'ENGINEERING_CANARY_ONLY' if not problems else 'CANNOT_CONFIRM_DIAGNOSTIC_DISCREPANCIES')
 print(json.dumps(clean(summary),ensure_ascii=False),flush=True)
 if problems:raise SystemExit(2)

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('phase',choices=['prepare','canary','full']);ap.add_argument('--workers',type=int,default=2);args=ap.parse_args()
 if args.phase=='prepare':prepare()
 else:run(args.phase,args.workers)
