from pathlib import Path
import json,datetime,time,sys,resource,hashlib
import consumer as C
H=Path(__file__).resolve().parent;run_id=datetime.datetime.now(datetime.timezone.utc).strftime('canary3_%Y%m%dT%H%M%SZ');start=time.monotonic();calls={'original_full_compute':0,'original_process_symbol':0,'step':0}
def profile(frame,event,arg):
 if event=='call':
  name=frame.f_code.co_name;path=frame.f_code.co_filename
  if name=='compute'and path.endswith('/formula/formula_engine.py'):calls['original_full_compute']+=1;raise RuntimeError('FORBIDDEN_ORIGINAL_FULL_COMPUTE')
  if name=='process_symbol'and path.endswith('/pipeline_v4.py'):calls['original_process_symbol']+=1;raise RuntimeError('FORBIDDEN_ORIGINAL_PROCESS_SYMBOL')
  if name=='step'and path.endswith('/state_consumer_v1/state_engine.py'):calls['step']+=1
sys.setprofile(profile);ctx=C.Consumer(run_id);results=[];failures=[]
for symbol in ('002608.SZ','000001.SZ','300053.SZ'):
 t=time.monotonic();before=calls.copy()
 try:
  item=ctx.run_one(symbol);pages=[];cursor=None
  while True:
   page=ctx.inspect(symbol,limit=500,before_date=cursor);pages=page['rows']+pages;cursor=page['next_before_date']
   if cursor is None:break
  old=json.loads(__import__('gzip').decompress(C.W.read_bound(C.R/item['old_formula']['path'],item['old_formula'])))['rows'];pair=ctx.journal.read(symbol,20261027)
  assert pages==old+[pair['daily']];assert len({r['trade_date']for r in pages})==len(pages)
  results.append({'symbol':symbol,'route':item['route'],'elapsed_seconds':time.monotonic()-t,'all_history_pagination_exact':True,'total_rows':len(pages),'calls':{k:calls[k]-before[k]for k in calls},'daily_sha256':item['daily_sha256'],'state_sha256':item['state_sha256']});print(symbol,results[-1],flush=True)
 except Exception as e:
  failures.append({'symbol':symbol,'error':type(e).__name__+': '+str(e)});print(failures[-1],flush=True)
sys.setprofile(None)
summary={'status':'THREE_STOCK_CANDIDATE_PASS_PENDING_REVIEW'if not failures else'FAILED','run_id':run_id,'results':results,'failures':failures,'calls':calls,'elapsed_seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'network_calls':0,'root_scope_sha256':C.E.ROOT_SCOPE_SHA,'display_allowed':False,'code_hashes':{p.name:C.sha(p.read_bytes())for p in H.glob('*.py')}}
C.output(ctx.journal.root/'SUMMARY.json',summary);C.output(ctx.journal.root/'APPEND_INDEX.json',{'run_id':run_id,'entries':ctx.index,'code_hashes':summary['code_hashes'],'root_scope_sha256':C.E.ROOT_SCOPE_SHA,'research_consumption_allowed':False});print(json.dumps(summary,ensure_ascii=False));print('OUTPUT',ctx.journal.root)
