"""Task-only Mac launcher reusing frozen original R3 worker/evaluator without formula changes."""
import sys,json,hashlib,csv,time,importlib.util,resource
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import multiprocessing
sys.dont_write_bytecode=True
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D));from registry import sha,save,event
CONTRACT=D/'MAC_CONTRACT.json'
def work(task):
 binding,contract,codes,out=task
 name='today_original_r3'
 if name not in sys.modules:
  spec=importlib.util.spec_from_file_location(name,binding['original_r3']['path']);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
 return sys.modules[name].worker(task)
def main():
 c=json.loads(CONTRACT.read_text());b=json.loads((D/'MAC_INPUT_BINDING.json').read_text());start=json.loads((D/'registry/MAC_RUN_STARTED.json').read_text());assert start['contract_sha256']==sha(CONTRACT)
 for p,h in c['source_bindings'].items():assert sha(p)==h,'SOURCE_DRIFT:'+p
 p=Path(b['selector']['target_path']);s=p.stat();assert dict(inode=s.st_ino,mtime_ns=s.st_mtime_ns,size_bytes=s.st_size)==b['selector']['target_stat'],'PANEL_DRIFT'
 import pandas as pd
 a=pd.read_csv(D/'A_UNIVERSE.csv',dtype=str,encoding='utf-8-sig');assert sha(D/'A_UNIVERSE.csv')==b['universe_sha256'],'UNIVERSE_DRIFT'
 current=a[a.trade_date.eq(c['signal_date'])].sort_values('ts_code');stale=a[~a.trade_date.eq(c['signal_date'])].sort_values('ts_code');assert len(current)==c['expected_current_A_count'];stale.to_csv(D/'MAC_STALE_INPUT_EXCLUDED.csv',index=False,encoding='utf-8-sig')
 codes=current.ts_code.tolist();canary=[x for x in c['canary_codes'] if x in codes];out=D/'mac_run';out.mkdir(exist_ok=False);(out/'parts').mkdir();started=time.monotonic();parts=[]
 task=(b,c,canary,str(out/'parts/canary.jsonl'));part=work(task);parts.append(part);rows=[json.loads(line) for line in Path(part['path']).read_text().splitlines()];assert len(rows)==len(canary) and all(r['selected'] is not None for r in rows),'CANARY_UNEVALUABLE';save(out/'CANARY_RECEIPT.json',dict(part=part,codes=canary,selected=[r['ts_code'] for r in rows if r['selected']],basis='UNADJUSTED',formula_changed=False));event(CONTRACT,'CHECKPOINT','MAC_CANARY_COMPLETED',[out/'CANARY_RECEIPT.json',Path(part['path'])],{'formula_evaluations':len(canary),'unknown_count':0,'wall_seconds':part['wall_seconds']},'RUNNING');print(json.dumps({'stage':'MAC_CANARY_COMPLETED','count':len(canary),'selected':[r['ts_code'] for r in rows if r['selected']],'wall_seconds':part['wall_seconds']}),flush=True)
 remain=[x for x in codes if x not in canary];size=c['stock_chunk_size'];tasks=[(b,c,remain[i:i+size],str(out/'parts'/f'part_{i//size:04d}.jsonl')) for i in range(0,len(remain),size)];event(CONTRACT,'CHECKPOINT','MAC_FULL_STARTED',[out/'CANARY_RECEIPT.json'],{'remaining_formula_evaluations':len(remain),'workers':c['workers'],'stock_chunk_size':size},'RUNNING')
 with ProcessPoolExecutor(max_workers=c['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
  futures={pool.submit(work,task):i for i,task in enumerate(tasks)}
  for f in as_completed(futures):
   part=f.result();parts.append(part);checkpoint=out/'parts'/f'receipt_{futures[f]:04d}.json';save(checkpoint,part);event(CONTRACT,'CHECKPOINT',f'MAC_CHUNK_{futures[f]:04d}_COMPLETED',[checkpoint,Path(part['path'])],{'formula_evaluations':part['row_count'],'wall_seconds':part['wall_seconds'],'peak_rss_bytes':part['peak_rss_bytes']},'RUNNING');print(json.dumps({'stage':'MAC_CHUNK_COMPLETED','chunk':futures[f],'count':part['row_count']},ensure_ascii=False),flush=True)
 rows=[]
 for part in parts:
  assert sha(part['path'])==part['sha256'];rows.extend(json.loads(x) for x in Path(part['path']).read_text().splitlines())
 rows.sort(key=lambda x:x['ts_code']);assert [r['ts_code'] for r in rows]==codes,'FINAL_COVERAGE'
 names=dict(zip(current.ts_code,current.name));selected=[dict(code=r['ts_code'],name=names[r['ts_code']],signal_date=r['signal_date'],XG=r['XG'],observed_history_bars=r['observed_history_bars']) for r in rows if r['selected'] is True];unknown=[r for r in rows if r['selected'] is None]
 with (D/'MAC_A_CANDIDATES.csv').open('w',encoding='utf-8-sig',newline='') as stream:
  w=csv.DictWriter(stream,fieldnames=['code','name','signal_date','XG','observed_history_bars']);w.writeheader();w.writerows(selected)
 with (D/'MAC_A_SIGNALS.jsonl').open('w') as stream:
  for row in rows:stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
 save(D/'MAC_UNKNOWN.json',unknown)
 stat=p.stat();assert dict(inode=stat.st_ino,mtime_ns=stat.st_mtime_ns,size_bytes=stat.st_size)==b['selector']['target_stat'],'FINAL_PANEL_DRIFT'
 r=dict(status='MAC_EXECUTED_AWAITING_INDEPENDENT_REVIEW',selection_date='20261023',signal_date=c['signal_date'],execution_id=c['execution_id'],engine='Mac original R3 worker + original255 evaluator + delivered V192ORIG formula',price_basis='RAW_UNADJUSTED',history_start=c['history_start'],history_end=c['signal_date'],input_binding_sha256=sha(D/'MAC_INPUT_BINDING.json'),universe_count=len(codes),stale_input_excluded=len(stale),candidate_count=len(selected),candidates=selected,unknown_count=len(unknown),negative_count=len(rows)-len(selected)-len(unknown),formula_evaluations=len(rows),parts=parts,wall_seconds=time.monotonic()-started,parent_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,notes=['No current22-day QFQ bound; known raw-vs-QFQ formula differences remain','No Windows/HTTP/SSH calls in this Mac phase','No TopN or manual additions','Current panel D22 coverage5494;318 stale inputs excluded and separately listed','QFQ panel known locally onlythrough20261015; no new producer or data repair'],research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 save(D/'MAC_RESULT.json',r);(D/'MAC_A_CANDIDATES.md').write_text('2026-10-23盘前Mac本地研究候选\n\n信号日2026-10-22收盘；原公式；RAW_UNADJUSTED（不复权），窗口2026-01-01至10-22。按代码排序，无TopN、不表示买入顺序。\n\n'+f'计算{len(rows)}只，入选{len(selected)}只，未知{len(unknown)}只；318只陈旧输入单列排除。\n\n'+'|代码|名称|\n|---|---|\n'+''.join('|'+x['code']+'|'+x['name']+'|\n' for x in selected)+'\n既有本地QFQ仅到10月15日；本结果不是前复权选股。RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false\n')
 artifacts=[D/n for n in ['mac_selection.py','MAC_CONTRACT.json','MAC_INPUT_BINDING.json','MAC_RESULT.json','MAC_A_CANDIDATES.csv','MAC_A_CANDIDATES.md','MAC_A_SIGNALS.jsonl','MAC_UNKNOWN.json','MAC_STALE_INPUT_EXCLUDED.csv']];save(D/'MAC_ARTIFACT_MANIFEST.json',{'files':{str(p):sha(p) for p in artifacts},'parts':parts});snap=event(CONTRACT,'TERMINAL','MAC_TERMINAL',[D/'MAC_RESULT.json',D/'MAC_A_CANDIDATES.csv',D/'MAC_ARTIFACT_MANIFEST.json'],{'formula_evaluations':len(rows),'candidate_count':len(selected),'unknown_count':len(unknown),'stale_input_excluded':len(stale)},r['status']);save(D/'LEDGER.json',dict(worker='/root/today_selection_writer',milestone='MAC_LOCAL_SELECTION_TERMINAL',lifecycle_status='completed_pending_independent_review',registry=snap));print(json.dumps({'result':str(D/'MAC_RESULT.json'),'candidate_count':len(selected),'unknown_count':len(unknown),'registry':snap},ensure_ascii=False),flush=True)
if __name__=='__main__':
 try:main()
 except BaseException as exc:
  save(D/'MAC_EXECUTION_ERROR.json',dict(error_type=type(exc).__name__,error=str(exc)));event(CONTRACT,'TERMINAL','MAC_TERMINAL_FAILED',[D/'MAC_EXECUTION_ERROR.json'],{},'CANNOT_CONFIRM_MAC_EXECUTION');raise
