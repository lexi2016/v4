"""Today-only full-universe invocation of the original materializer.

Root registers before execution. Parallel workers only own disjoint immutable
stock checkpoints; the original parent materializer alone publishes completion.
"""
from pathlib import Path
import concurrent.futures
import json
import multiprocessing
import os
import resource
import subprocess
import runpy
import sys
import time
HERE=Path(__file__).resolve().parent
runpy.run_path(str(HERE/'run_real_canary.py'),run_name='candidate_source_imports')
from ops import research_panel_daily_product as product
_CONTEXT=None

def initialize(data_root,target,output_root):
 global _CONTEXT
 _CONTEXT=product.SourceContext(data_root,target);_CONTEXT.root=Path(output_root)

def checkpoint(symbol,path):
 try:
  row,cache,cachepath=product.compute_stock(_CONTEXT,symbol,history_dates=());product.save(cachepath,cache)
 except (ValueError,KeyError,TypeError,OSError) as error:
  if str(error).startswith('DAILY_SOURCE_PIN_DRIFT'):raise
  row=dict(symbol=symbol,display_name=None,data_date=str(_CONTEXT.target),groups='',pending_groups='|'.join(product.GROUPS),latest_new_anchor='',reasons='SOURCE_ISOLATED:'+str(error),risk_clear='UNKNOWN',evaluation={'groups':{g:{'status':'UNKNOWN','reasons':['SOURCE_ISOLATED:'+str(error)]} for g in product.GROUPS}},statistics=None,historical_coverage={'known_full_history':False,'evaluated_count':0,'missing':['SOURCE_ISOLATED']},qualification={'status':'UNKNOWN','reason':str(error)})
 _CONTEXT.unchanged();row.update(product.FLAGS);ref=product.save(Path(path),row,immutable=True)
 return {'symbol':symbol,'ref':ref,'groups':row['groups'],'pending_groups':row['pending_groups'],'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'python':sys.executable}

if __name__=='__main__':
 pins=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True);workers=int(pins.get('workers',4));assert 1<=workers<=4
 for ref in [*pins['pointers'],pins['receipt'],pins['snapshot'],pins['quarantine'],*pins['code']]:product.checked(ref)
 product.save(out/'RUN_BINDING.json',pins,immutable=True)
 started=time.perf_counter();context=product.SourceContext(pins['data_root'],pins['target']);context.root=out/'daily_products/a_share';selected=sorted(context.scope)
 assert context.generation==pins['generation'] and len(selected)==pins['expected_universe_count'] and set(selected)==set(pins['universe']), 'FULL_SCOPE_IDENTITY_CONFLICT'
 runkey=product.digest(dict(identity=context.identity,config=context.config_ref,symbols=selected,history_dates=[]));parts=context.root/'checkpoints'/str(context.target)/runkey;pending=[];complete=[]
 for symbol in selected:
  path=parts/(symbol+'.json')
  if path.is_file():
   row=json.loads(path.read_text());assert row['symbol']==symbol and row['data_date']==str(context.target);complete.append(symbol)
  else:pending.append((symbol,str(path)))
 product.save(out/'PROGRESS.json',dict(completed=len(complete),total=len(selected),generation=context.generation,history_dates=[],workers=workers))
 reference_symbols=list(pins['reference_rows']);guard_limit=24*1024**3;peak_rss=0
 def rss_bytes():
  pids=[os.getpid()]+[p.pid for p in multiprocessing.active_children() if p.pid]
  text=subprocess.run(['ps','-o','rss=','-p',','.join(map(str,pids))],capture_output=True,text=True,check=True).stdout
  return sum(int(x.strip()) for x in text.splitlines() if x.strip())*1024
 def verify_current(symbol,path):
  row=json.loads(Path(path).read_text());reference=pins['reference_rows'][symbol];expected=json.loads(product.checked(reference).read_text())
  fields=('symbol','display_name','data_date','groups','pending_groups','latest_new_anchor','reasons','risk_clear','evaluation','qualification')
  assert all(row[k]==expected[k] for k in fields),'CURRENT_WORKER_PARITY_FAILED:'+symbol
  assert row['statistics']['price_distribution']==expected['statistics']['price_distribution'],'PRICE_DISTRIBUTION_PARITY_FAILED:'+symbol
 with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),initializer=initialize,initargs=(pins['data_root'],pins['target'],str(context.root))) as pool:
  # Only three cross-market tasks exist before this gate; no other stock starts.
  initial={pool.submit(checkpoint,symbol,str(parts/(symbol+'.json'))):symbol for symbol in reference_symbols if symbol not in complete}
  for future in concurrent.futures.as_completed(initial):
   symbol=initial[future];result=future.result();assert result['symbol']==symbol and result['python']==pins['python'];complete.append(symbol)
  for symbol in reference_symbols:verify_current(symbol,parts/(symbol+'.json'))
  peak_rss=max(peak_rss,rss_bytes());assert peak_rss<=guard_limit,'RSS_GUARD_24GiB'
  product.save(out/'INITIAL_3_WORKER_PARITY.json',dict(status='PASS',symbols=reference_symbols,fields='complete current evaluation/qualification/price distribution',peak_rss_bytes=peak_rss,**product.FLAGS))
  iterator=iter((symbol,path) for symbol,path in pending if symbol not in reference_symbols);futures={};guard_exceeded=False
  def submit_next():
   if guard_exceeded:return False
   try:symbol,path=next(iterator)
   except StopIteration:return False
   futures[pool.submit(checkpoint,symbol,path)]=symbol;return True
  for _ in range(workers*2):submit_next()
  while futures:
   done,_=concurrent.futures.wait(futures,return_when=concurrent.futures.FIRST_COMPLETED)
   peak_rss=max(peak_rss,rss_bytes());guard_exceeded=peak_rss>guard_limit
   for future in done:
    symbol=futures.pop(future);result=future.result();assert result['symbol']==symbol and result['python']==pins['python'];complete.append(symbol)
    product.save(out/'PROGRESS.json',dict(completed=len(complete),total=len(selected),generation=context.generation,history_dates=[],workers=workers,last_symbol=symbol,last_groups=result['groups'],last_unknown=result['pending_groups'],wall_seconds=time.perf_counter()-started,peak_cumulative_rss_bytes=peak_rss,guard_exceeded=guard_exceeded))
    if len(complete)%100==0:print(json.dumps({'completed':len(complete),'total':len(selected),'wall_seconds':time.perf_counter()-started,'peak_cumulative_rss_bytes':peak_rss}),flush=True)
    submit_next()
  if guard_exceeded:raise MemoryError('RSS_GUARD_24GiB_NO_NEW_TASKS_AFTER_GUARD_EXISTING_TASKS_DRAINED')
 context.unchanged();assert set(complete)==set(selected)
 # Requires only the explicit context injection; normal producer default stays unchanged.
 result=product.materialize_daily_product(data_root=pins['data_root'],target=pins['target'],output_root=context.root,history_dates=())
 manifest=json.loads(Path(result['manifest']['path']).read_text());artifact=json.loads(Path(result['artifact']['path']).read_text());assert artifact['sample_only'] is False and artifact['processed_count']==len(selected)==artifact['source_universe_count']
 groups={g:[r for r in artifact['rows'] if g in r['groups'].split('|')] for g in product.GROUPS};unknown=[]
 for symbol in selected:
  row=json.loads(Path(artifact['row_refs'][symbol]['path']).read_text())
  if row['pending_groups']:unknown.append({k:row[k] for k in ('symbol','display_name','pending_groups','reasons')})
 product.save(out/'GROUPS_AND_UNKNOWN.json',dict(data_date=str(context.target),source_generation=context.generation,processed_count=len(selected),unique_count=artifact['unique_count'],groups=groups,unknown=unknown,**product.FLAGS))
 product.save(out/'RESULT.json',dict(status='FULL_5808_NUMERIC_COMPLETED',result=result,group_counts=artifact['group_counts'],unique_count=artifact['unique_count'],unknown_count=len(unknown),wall_seconds=time.perf_counter()-started,workers=workers,peak_cumulative_rss_bytes=peak_rss,history_dates=[],historical_bootstrap=False,**product.FLAGS))
