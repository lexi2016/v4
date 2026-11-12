"""D12 one-batch glue around unchanged live original daily kernel; not a producer.
Writes only this research batch. Original history labels are read; sqlite cache is
an online read-only source backup in the batch namespace. No canonical writes.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
import concurrent.futures as cf,datetime,hashlib,json,multiprocessing,pathlib,plistlib,resource,sqlite3,sys,time,traceback
N=pathlib.Path(__file__).resolve().parents[1];DATE=20261112
CTX=None;PAR=None;PROD=None;SOURCES=None

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):
 p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.pending');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n');os.replace(tmp,p)
def setup_env(env):
 os.environ.update(env);os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.path.insert(0,env['V4_APP_ROOT'])
def initialize(env,root,parts,identity,config_ref,scope,sources,lock):
 global CTX,PAR,PROD,SOURCES
 setup_env(env)
 from ops import research_daily_product_parallel as par,research_panel_daily_product as prod
 par.initialize(env['V4_RESEARCH_PANEL_A_DATA_ROOT'],DATE,root,parts,identity,config_ref,scope,sources,lock,False)
 CTX=par._CONTEXT;PAR=par;PROD=prod;SOURCES=sources
 original=CTX.engine().compute;CTX._research_compute_calls=0
 def counted(*a,**k):CTX._research_compute_calls+=1;return original(*a,**k)
 CTX.engine().compute=counted

def work(symbol):
 proof=N/'engine_proofs'/(symbol+'.json');before=CTX._research_compute_calls;t=time.perf_counter();cpu=time.process_time()
 result=PAR.checkpoint(symbol);row=json.loads(PROD.checked(result['ref']).read_bytes())
 calls=CTX._research_compute_calls-before
 if 'same_day_formula_reuse' in row:raise RuntimeError('FRESH_ENGINE_FORBIDS_SAME_DAY_FORMULA_REUSE')
 accepted=row['qualification'].get('status')=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
 if accepted and calls!=1:raise RuntimeError('ACCEPTED_SYMBOL_ENGINE_CALL_COUNT:'+symbol+':'+str(calls))
 p=dict(symbol=symbol,target_date=DATE,generation=CTX.generation,pid=os.getpid(),engine_compute_calls=calls,original_kernel_called=True,wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-cpu,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,row=result['ref'],qualification=row['qualification'],fresh_namespace=True,new_fit_count=0)
 save(proof,p);return p

def main():
 live=pathlib.Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist');env=plistlib.loads(live.read_bytes())['EnvironmentVariables'];setup_env(env)
 from ops import research_daily_product_parallel as par,research_panel_daily_product as prod
 scope=json.loads((N/'SCOPE.json').read_text());assert scope['NEW_FIT_COUNT']==0 and scope['source_date']=='2026-11-12'
 assert sha(N/'P5_14_6_TRAINING_MASTER_CN_20261110.remote_baseline.md')=='83dd962a5650e8314127f4c5e76909b1069435ba3046bc5063949975906a7e10'
 root=N/'original_kernel_namespace';root.mkdir(exist_ok=True);clone=N/'cache/event_outcomes.sqlite3';clone.parent.mkdir(exist_ok=True)
 source=pathlib.Path(env['V4_RESEARCH_EVENT_CASE_CACHE'])
 if not clone.exists():
  source_db=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);dest=sqlite3.connect(clone);source_db.backup(dest);dest.close();source_db.close()
 env['V4_RESEARCH_EVENT_CASE_CACHE']=str(clone);setup_env(env)
 context=prod.SourceContext(env['V4_RESEARCH_PANEL_A_DATA_ROOT'],DATE);context.root=root
 assert context.target==DATE and context.identity['basis']['price_basis']=='QFQ_ASOF'
 selected=sorted(context.scope);parts=par.checkpoint_parts(context,selected);parts.mkdir(parents=True,exist_ok=True);sources=par.bound_main_sources()
 freeze=dict(status='FROZEN_BEFORE_D12_FRESH_COMPUTE',D=DATE,cutoff=scope['information_cutoff'],observed_at=datetime.datetime.now().astimezone().isoformat(),scope_sha256=sha(N/'SCOPE.json'),script_sha256=sha(__file__),env=env,source_binding=sources,source_identity=context.identity,source_config=context.config_ref,selector=prod.reference(context.panel),receipt=context.receipt_ref,snapshot=context.snapshot_ref,quarantine=context.quarantine_ref,scope=selected,scope_count=len(selected),parts=str(parts),output_root=str(root),history_dates=[],cache_backup=dict(source=str(source),source_stat=list(source.stat()),backup=str(clone),backup_initial_sha256=sha(clone)),kernel='original research_daily_product_parallel.checkpoint -> original compute_stock -> original formula engine.compute; same-day retained formula source absent in isolated namespace',NEW_FIT_COUNT=0,**prod.FLAGS)
 fp=N/'RUN_FREEZE.json'
 if fp.exists():
  old=json.loads(fp.read_text());assert all(old[k]==freeze[k] for k in ('source_identity','source_config','selector','receipt','snapshot','quarantine','scope','parts','output_root','script_sha256')),'RESUME_IDENTITY_DRIFT'
 else:save(fp,freeze)
 # Three markets, fixed before reading results. Canary proofs resume exact same
 # actual calls after interruption; no successful checkpoint is recomputed twice.
 canaries=['601689.SH','002371.SZ','920001.BJ'];assert set(canaries)<=set(selected)
 ctx=multiprocessing.get_context('spawn');lock=ctx.Lock();initialize(env,str(root),str(parts),context.identity,context.config_ref,selected,sources,lock)
 t=time.perf_counter();initial=par.memory_state();canary=[]
 for symbol in canaries:
  proof=N/'engine_proofs'/(symbol+'.json')
  if proof.exists():p=json.loads(proof.read_text());prod.checked(p['row']);assert p['generation']==context.generation
  else:p=work(symbol)
  canary.append(p)
 assert {p['symbol'][-2:] for p in canary}=={'SH','SZ','BJ'} and all(p['original_kernel_called'] for p in canary)
 save(N/'CANARY_ENGINE_PASS.json',dict(status='PASS_3_MARKET_ORIGINAL_FRESH_KERNEL',samples=canary,source_binding=sources,fit_attempts=0))
 print(json.dumps(dict(status='CANARY_PASS',completed=len(canary),symbols=canaries,seconds=time.perf_counter()-t)),flush=True)
 completed={p.stem for p in (N/'engine_proofs').glob('*.json')};pending=[s for s in selected if s not in completed]
 resources=par.resource_plan(par.memory_state(),max(1,len(pending)));resources['memory_guard_bytes']=min(resources['memory_guard_bytes'],64*1024**3)
 resources['canary_peak_worker_rss_bytes']=max(p['peak_rss_bytes'] for p in canary)
 save(N/'RESOURCE_PLAN.json',resources);peak=resources['observed']['cumulative_rss_bytes'];failure=None;cpu_sum=sum(json.loads(p.read_text())['cpu_seconds'] for p in (N/'engine_proofs').glob('*.json'))
 progress=dict(status='RUNNING',total=len(selected),completed=len(completed),resources=resources,start_epoch=time.time(),source_generation=context.generation,canary_pass=True,NEW_FIT_COUNT=0)
 save(N/'ENGINE_PROGRESS.json',progress)
 if pending:
  with cf.ProcessPoolExecutor(max_workers=resources['workers'],mp_context=ctx,initializer=initialize,initargs=(env,str(root),str(parts),context.identity,context.config_ref,selected,sources,lock)) as pool:
   iterator=iter(pending);inflight={}
   def submit():
    if failure:return
    try:symbol=next(iterator)
    except StopIteration:return
    inflight[pool.submit(work,symbol)]=symbol
   for _ in range(min(resources['max_pending'],len(pending))):submit()
   sampled=time.monotonic()
   while inflight:
    done,_=cf.wait(inflight,return_when=cf.FIRST_COMPLETED)
    if time.monotonic()-sampled>=30:
     observed=par.memory_state();sampled=time.monotonic();peak=max(peak,observed['cumulative_rss_bytes'])
     if observed['cumulative_rss_bytes']>resources['memory_guard_bytes'] or observed['available_bytes']<resources['reserve_available_bytes']:failure=MemoryError('RESOURCE_GUARD_DRAINED')
    for f in done:
     symbol=inflight.pop(f)
     try:p=f.result();completed.add(symbol);cpu_sum+=p['cpu_seconds']
     except BaseException as error:failure=error;save(N/('FAILURE_'+symbol+'.json'),dict(symbol=symbol,error=str(error),traceback=traceback.format_exc()))
     progress.update(completed=len(completed),last_symbol=symbol,wall_seconds=time.perf_counter()-t,task_cpu_seconds=cpu_sum,peak_cumulative_rss_bytes=peak,stop_new_submissions=failure is not None);save(N/'ENGINE_PROGRESS.json',progress)
    for _ in done:submit()
 if failure:raise failure
 assert completed==set(selected),'MISSING_FRESH_SYMBOL_PROOFS';context.unchanged()
 progress.update(status='FRESH_FULL_UNIVERSE_COMPLETE',wall_seconds=time.perf_counter()-t,completed=len(completed),task_cpu_seconds=cpu_sum,peak_cumulative_rss_bytes=peak,engine_compute_calls=sum(json.loads(p.read_text())['engine_compute_calls']for p in (N/'engine_proofs').glob('*.json')));save(N/'ENGINE_PROGRESS.json',progress)
 print(json.dumps(progress),flush=True)
if __name__=='__main__':
 try:main()
 except BaseException as e:save(N/'ENGINE_RUN_FAILURE.json',dict(error_type=type(e).__name__,error=str(e),traceback=traceback.format_exc()));raise
