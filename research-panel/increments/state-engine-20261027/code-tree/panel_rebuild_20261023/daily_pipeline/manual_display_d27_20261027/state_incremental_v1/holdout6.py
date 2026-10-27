"""Exactly six cached stocks. Future oracle rows are never passed to bootstrap; no fullformula calls."""
from pathlib import Path
import json,gzip,hashlib,datetime,importlib.util,time,resource,shutil
H=Path(__file__).resolve().parent;R=H.parents[3];B=H.parents[1];D=B/'daily_runs/staging/20261026_cbc6d4b2475d9793a1bf'
def loadmod(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
E=loadmod('state_holdout',H/'state_engine.py');J=loadmod('state_holdout_journal',H/'journal.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_bytes(E.canonical(obj))
run_id=datetime.datetime.now(datetime.timezone.utc).strftime('holdout6_%Y%m%dT%H%M%SZ');out=H/run_id;out.mkdir();started=time.monotonic();receipt=json.load(open(D/'RECEIPT.json'));manifest=json.load(open(D/'PARTITION_MANIFEST.json'));plan=json.load(open(D/'PLAN.json'));policy=B.parent/'cache/READ_INVALIDATIONS.json';calendar_path=B/'CALENDAR_20261023_1231_VERIFIED_V2.json';calendar=json.load(open(calendar_path));results=[];failures=[];source_records={};symbols=sorted(E.ALLOWED_SYMBOLS)
for symbol in symbols:
 spec=next(x for x in receipt['stocks'][symbol]['files']if x['path']==f'stocks/{symbol}/formula.json.gz');path=D/spec['path'];assert path.stat().st_size==spec['bytes']and sha(path)==spec['sha256'];source_records[symbol]={**spec,'absolute_path':str(path),'source_root':str(D)};allrows=json.loads(gzip.decompress(path.read_bytes()))['rows'];assert allrows[-1]['trade_date']==20261026
 cases=[('recent_offline',next(i for i,r in enumerate(allrows)if r['trade_date']==20261019),[20261020,20261021,20261022,20261023,20261026]),('verified_calendar',next(i for i,r in enumerate(allrows)if r['trade_date']==20261023),[20261026])]
 if symbol in ('301686.SZ','301655.SZ'):cases.append(('early_warmup_offline',0,[r['trade_date']for r in allrows[1:12]]))
 for case,cut,targets in cases:
  prefix=allrows[:cut+1];dates=[r['trade_date']for r in allrows]
  contract={'kind':'CACHED_ADJACENT_SEQUENCE_ONLY_NOT_CALENDAR_ADMITTED','open_dates':dates}
  if case=='verified_calendar':contract={'kind':'VERIFIED_CALENDAR_RESEARCH_CANDIDATE','open_dates':[int(x)for x in calendar['open_dates']],'coverage_start':calendar['coverage_start'],'coverage_end':calendar['coverage_end'],'calendar_sha256':sha(calendar_path)}
  binding={'symbol':symbol,'purpose':'SIX_STOCK_CACHED_HOLDOUT_ALGORITHM_ONLY','price_coordinate':'FIXED_VINTAGE_QFQ_NONPIT','event_sha256':plan['source_bindings']['events']['sha256'],'policy_sha256':sha(policy),'source_formula_sha256':spec['sha256'],'volume_contract_sha256':hashlib.sha256(E.canonical(manifest['volume_contract'])).hexdigest(),'bootstrap_prefix_sha256':hashlib.sha256(E.canonical(prefix)).hexdigest(),'date_contract':contract}
  journal=J.Journal(run_id+'_'+case);boot_start=time.perf_counter();state=E.bootstrap(symbol,prefix,prefix[-1]['trade_date'],binding);bootstrap_seconds=time.perf_counter()-boot_start;case_out=out/symbol/case;case_out.mkdir(parents=True);save(case_out/'BOOTSTRAP_STATE.json',state);save(case_out/'BINDING.json',binding);immutable_hash=hashlib.sha256(E.canonical(prefix)).hexdigest();steps=[]
  try:
   for target in targets:
    oracle=next(r for r in allrows if r['trade_date']==target);step_start=time.perf_counter();row,new=E.step(state,oracle['ohlcv'],binding);step_seconds=time.perf_counter()-step_start
    if row!=oracle:
     mismatch={'date':target,'values':{k:{'expected':oracle['values'].get(k),'actual':row['values'].get(k)}for k in oracle['values']if row['values'].get(k)!=oracle['values'][k]},'drawings':[{'expected':a,'actual':b}for a,b in zip(oracle['drawings'],row['drawings'])if a!=b],'ohlcv_equal':row['ohlcv']==oracle['ohlcv']};save(case_out/f'FAIL_{target}.json',mismatch);raise ValueError('ORIGINAL_DAILY_MISMATCH')
    commit=journal.commit(symbol,row,new);reloaded=journal.read(symbol,target);assert reloaded['daily']==oracle and reloaded['state']==new;state=json.loads(E.canonical(reloaded['state']));steps.append({'date':target,'step_compute_seconds':step_seconds,'all51_22_exact':True,'row_sha256':hashlib.sha256(E.canonical(row)).hexdigest(),'state_sha256':state['state_sha256'],'pair_status':commit['status'],'old_history_recomputed':0});assert hashlib.sha256(E.canonical(prefix)).hexdigest()==immutable_hash
   result={'symbol':symbol,'case':case,'bootstrap_cutoff':prefix[-1]['trade_date'],'bootstrap_rows':len(prefix),'bootstrap_seconds':bootstrap_seconds,'steps':steps,'date_contract_kind':contract['kind'],'state_reload_every_step':True,'old_history_untouched':True,'status':'CANDIDATE_HOLDOUT_EXACT_PENDING_INDEPENDENT_REVIEW'};results.append(result);save(case_out/'RESULT.json',result);print(symbol,case,len(steps),'PASS',flush=True)
  except Exception as ex:
   failure={'symbol':symbol,'case':case,'error':type(ex).__name__+': '+str(ex),'completed_steps':steps};failures.append(failure);save(case_out/'FAILURE.json',failure);print(failure,flush=True)
for symbol,sp in source_records.items():assert sha(D/sp['path'])==sp['sha256']
summary={'status':'SIX_STOCK_HOLDOUT_CANDIDATE_PASS'if not failures else'SIX_STOCK_HOLDOUT_FAILED','run_id':run_id,'stock_count':6,'case_count':len(results)+len(failures),'successful_day_steps':sum(len(r['steps'])for r in results),'results':results,'failures':failures,'source_bindings':source_records,'implementation_sha256':sha(H/'state_engine.py'),'journal_sha256':sha(H/'journal.py'),'original_engine_sha256':E.ENGINE_SHA,'formula_calls_full_history':0,'network_calls':0,'fit_calls':0,'business_D27_rows_recomputed':0,'historical_assigned51_recomputed':0,'only3_hidden_EMA_bootstrap_scans':True,'not_PIT_certified':True,'reader_admission':False,'elapsed_seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'free_bytes':shutil.disk_usage(H).free};save(out/'SUMMARY.json',summary);print(json.dumps({k:v for k,v in summary.items()if k not in ('results','source_bindings')},ensure_ascii=False));print('OUTPUT',out)
