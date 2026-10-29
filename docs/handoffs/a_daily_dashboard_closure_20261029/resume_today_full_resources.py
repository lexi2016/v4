"""Resource-only resume of the frozen today runner; no source/math changes."""
from pathlib import Path
import concurrent.futures
import importlib.util
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('frozen_today_executor',HERE/'run_today_full.py')
executor=importlib.util.module_from_spec(spec);sys.modules[spec.name]=executor;spec.loader.exec_module(executor)
product=executor.product

def memory_state():
 pids=[os.getpid()]+[p.pid for p in multiprocessing.active_children() if p.pid]
 rss=subprocess.run(['ps','-o','rss=','-p',','.join(map(str,pids))],capture_output=True,text=True,check=True).stdout
 pressure=subprocess.run(['memory_pressure'],capture_output=True,text=True,check=True).stdout
 match=re.search(r'System-wide memory free percentage:\s*(\d+)%',pressure)
 if not match:raise RuntimeError('MEMORY_PRESSURE_UNAVAILABLE')
 total=int(subprocess.run(['sysctl','-n','hw.memsize'],capture_output=True,text=True,check=True).stdout)
 return dict(cumulative_rss_bytes=sum(int(x.strip()) for x in rss.splitlines() if x.strip())*1024,memory_pressure_free_percent=int(match[1]),memory_pressure_estimated_free_bytes=total*int(match[1])//100,physical_memory_bytes=total)

if __name__=='__main__':
 execution=json.loads(Path(sys.argv[1]).read_text());product.checked(execution['adapter']);assert Path(execution['adapter']['path']).resolve()==Path(__file__).resolve();resources=json.loads(product.checked(execution['resource_config']).read_text());pins=json.loads(product.checked(execution['original_inputs']).read_text());out=Path(execution['output_root']).resolve();started=time.perf_counter()
 for ref in pins['code']:product.checked(ref)
 product.checked(execution['original_run_binding']);product.checked(execution['checkpoint_cut']);product.checked(execution['initial_parity_proof'])
 assert json.loads((out/'RUN_BINDING.json').read_text())==pins,'ORIGINAL_RUN_BINDING_CHANGED'
 assert json.loads(Path(execution['initial_parity_proof']['path']).read_text())['status']=='PASS','PRIOR_3_WORKER_PARITY_NOT_PASS'
 workers=resources['workers'];max_pending=resources['max_pending'];guard=resources['memory_guard_bytes'];reserve=resources['reserve_available_bytes']
 assert workers==14 and max_pending==28 and guard==64*1024**3 and reserve==24*1024**3,'UNAPPROVED_RESOURCE_CONFIG'
 product.save(out/'RESOURCE_EXECUTION_BINDING.json',execution,immutable=True)
 cut=json.loads(Path(execution['checkpoint_cut']['path']).read_text());cut_symbols=set()
 for item in cut['checkpoints']:product.checked(item);cut_symbols.add(item['symbol'])
 context=product.SourceContext(pins['data_root'],pins['target']);context.root=out/'daily_products/a_share';selected=sorted(context.scope)
 assert context.generation==pins['generation'] and selected==pins['universe'] and len(selected)==5808,'SCOPE_OR_GENERATION_CHANGED'
 runkey=product.digest(dict(identity=context.identity,config=context.config_ref,symbols=selected,history_dates=[]));parts=context.root/'checkpoints'/str(context.target)/runkey
 assert runkey==cut['checkpoint_runkey'],'CHECKPOINT_RUNKEY_CHANGED'
 complete=[];pending=[]
 for symbol in selected:
  p=parts/(symbol+'.json')
  if p.is_file():
   row=json.loads(p.read_text());assert row['symbol']==symbol and row['data_date']=='20261029';complete.append(symbol)
  else:pending.append((symbol,str(p)))
 assert cut_symbols<=set(complete) and len(complete)==cut['actual_completed_count'],'CHECKPOINT_CUT_CHANGED'
 base_completed=len(complete);observed=memory_state();peak=observed['cumulative_rss_bytes'];assert peak<=guard and observed['memory_pressure_estimated_free_bytes']>=reserve,'RESOURCE_PREFLIGHT_GUARD'
 product.save(out/'RESOURCE_PROGRESS.json',dict(completed=base_completed,total=5808,resumed_completed=0,remaining=len(pending),workers=workers,max_pending=max_pending,history_dates=[],prior_3_parity='REUSED_PASS',memory=observed,reason='USER_REQUESTED_RESOURCE_AND_CACHE_REBIND'))
 with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),initializer=executor.initialize,initargs=(pins['data_root'],pins['target'],str(context.root))) as pool:
  iterator=iter(pending);futures={};guard_exceeded=False
  def submit_next():
   if guard_exceeded:return
   try:symbol,path=next(iterator)
   except StopIteration:return
   futures[pool.submit(executor.checkpoint,symbol,path)]=symbol
  for _ in range(max_pending):submit_next()
  while futures:
   done,_=concurrent.futures.wait(futures,return_when=concurrent.futures.FIRST_COMPLETED)
   observed=memory_state();peak=max(peak,observed['cumulative_rss_bytes']);guard_exceeded=peak>guard or observed['memory_pressure_estimated_free_bytes']<reserve
   for future in done:
    symbol=futures.pop(future);result=future.result();assert result['symbol']==symbol and result['python']==pins['python'];complete.append(symbol)
    state=dict(completed=len(complete),total=5808,resumed_completed=len(complete)-base_completed,workers=workers,max_pending=max_pending,history_dates=[],last_symbol=symbol,last_groups=result['groups'],last_unknown=result['pending_groups'],wall_seconds=time.perf_counter()-started,peak_cumulative_rss_bytes=peak,memory=observed,guard_exceeded=guard_exceeded,prior_3_parity='REUSED_PASS')
    product.save(out/'RESOURCE_PROGRESS.json',state);product.save(out/'PROGRESS.json',state)
    if len(complete)%100==0:print(json.dumps(state),flush=True)
    submit_next()
  if guard_exceeded:raise MemoryError('RESOURCE_GUARD_NO_NEW_SUBMISSIONS_INFLIGHT_DRAINED')
 context.unchanged();assert set(complete)==set(selected) and len(complete)==5808
 result=product.materialize_daily_product(data_root=pins['data_root'],target=pins['target'],output_root=context.root,history_dates=())
 artifact=json.loads(product.checked(result['artifact']).read_text());assert artifact['sample_only'] is False and artifact['processed_count']==5808==artifact['source_universe_count']
 groups={g:[r for r in artifact['rows'] if g in r['groups'].split('|')] for g in product.GROUPS};unknown=[]
 for symbol in selected:
  row=json.loads(product.checked(artifact['row_refs'][symbol]).read_text())
  if row['pending_groups']:unknown.append({k:row[k] for k in ('symbol','display_name','pending_groups','reasons')})
 product.save(out/'GROUPS_AND_UNKNOWN.json',dict(data_date='20261029',source_generation=context.generation,processed_count=5808,unique_count=artifact['unique_count'],groups=groups,unknown=unknown,**product.FLAGS))
 product.save(out/'RESULT.json',dict(status='FULL_5808_NUMERIC_COMPLETED',result=result,group_counts=artifact['group_counts'],unique_count=artifact['unique_count'],unknown_count=len(unknown),resource_execution=execution,base_completed_reused=base_completed,newly_computed=len(complete)-base_completed,wall_seconds=time.perf_counter()-started,workers=workers,peak_cumulative_rss_bytes=peak,history_dates=[],historical_bootstrap=False,**product.FLAGS))
