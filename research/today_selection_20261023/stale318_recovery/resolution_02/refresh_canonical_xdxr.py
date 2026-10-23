"""Serial bounded same-owner event refresh. Each completed code is immutable and reusable."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def save(p,x):
 p=Path(p);assert not p.exists();p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=load(cp);b=c['input_identity'];out=Path(c['output_directory']);started=time.monotonic();results=[];calls=0;stop=None
 def fence(event,args):
  if event.startswith(('sqlite3.connect','subprocess.Popen')):raise RuntimeError('NO_OTHER_IO')
  if event=='socket.connect':assert args[1]==(c['host'],c['port']),'HOST_NOT_FROZEN'
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
   p=Path(os.fsdecode(args[0])).resolve();root=Path(b['registry_helper_directory']).parent.parent;d=Path(b['registry_helper_directory']);admin={root/'contracts/EXPERIMENT_REGISTRY.jsonl',root/'contracts/.EXPERIMENT_REGISTRY.jsonl.lock',root/'contracts/ACTIVE_RESEARCH_INDEX.json',root/'contracts/ACTIVE_RESEARCH_INDEX.today.tmp',root/'CURRENT_STATE.md',root/'HK_OHLCV_RESEARCH_STATE.md',root/'PROGRESS.md'};assert out.resolve() in p.parents or p in admin or p.parent==d/'registry','WRITE_BOUNDARY'
 sys.addaudithook(fence);sys.path.insert(0,b['owner_worktree']);from ops import a_share_daily_sync as owner
 sys.path.insert(0,b['registry_helper_directory']);from mac_registry import register
 targets=load(b['target_list'])['targets'];assert len(targets)==c['expected_target_count'] and len({r['code'] for r in targets})==len(targets)
 bycode={r['code']:r for r in targets};reuses=b['reuse_current_captures'];pending=[bycode[code] for code in c['capability_control_codes'] if code not in reuses]+[r for r in targets if r['code'] not in reuses and r['code'] not in c['capability_control_codes']]
 def validate_response(code,response):
  assert isinstance(response,list),'NONE_OR_UNKNOWN_SCHEMA_NOT_ZERO_EVENTS';dates=[]
  for row in response:
   assert isinstance(row,dict);d=int(row['year'])*10000+int(row['month'])*100+int(row['day']);datetime.strptime(str(d),'%Y%m%d');dates.append(d)
  return {'event_rows':len(response),'event_rows_le_D22':sum(d<=20261022 for d in dates),'event_rows_after_D22_metadata_only':sum(d>20261022 for d in dates),'latest_event_date':max(dates) if dates else None,'complete_typed_response':True,'zero_events_accepted_only_from_complete_successful_list':not response}
 for code,ref in reuses.items():
  assert code in bycode and sha(ref['path'])==ref['sha256'];x=load(ref['path']);response=x['response_rows'];assert x['response_error'] is None
  if 'request' in x:assert x['request']['code']==code.split('.')[0] and x['request']['market']==bycode[code]['market']
  results.append({'code':code,'market':bycode[code]['market'],'status':'REUSED_CURRENT_SUCCESS_CAPTURE','source_path':ref['path'],'source_sha256':ref['sha256'],'response_format':'response_rows','requests_this_execution':0,**validate_response(code,response)})
 def checkpoint(label):
  snapshot=out/('PROGRESS_'+label+'.json');elapsed=time.monotonic()-started;save(snapshot,{'results':results,'requests':calls,'target_count':len(targets),'elapsed_seconds':elapsed,'requests_per_second':calls/elapsed if elapsed else None,'stop_reason':stop,'source_writes':0});s=register(cp,'CHECKPOINT','XDXR58_'+label,[snapshot],{'captured_or_reused':len(results),'requests':calls,'target_count':len(targets),'elapsed_seconds':elapsed},'EVENT_REFRESH_CHECKPOINT_ONLY_NOT_INPUT_PROMOTION');save(out/('CHECKPOINT_'+label+'.json'),s);print(json.dumps({'checkpoint':label,'completed':len(results),'requests':calls,'elapsed_seconds':round(elapsed,3),'event_sha256':s['event_sha256']},ensure_ascii=False),flush=True)
 api=None
 try:
  for index,target in enumerate(pending):
   if time.monotonic()-started>=c['run_budget_seconds']:stop='BOUND_RUNTIME_REACHED_REMAINDER_NOT_REQUESTED';break
   if api is None:
    api=owner._runtime_api_factory(c['host'],c['port'])
    try:
     with owner._deadline_guard(c['connect_budget_seconds'],scope='CONNECT'):owner._connect_session(api,c['host'],c['port'],c['socket_timeout_seconds'])
    except Exception as e:stop='CONNECT_FAILED:'+type(e).__name__+':'+str(e);break
   code=target['code'];assert calls<c['request_budget'];observed=datetime.now(timezone.utc).isoformat();error=None;response=None
   try:
    calls+=1
    with owner._deadline_guard(c['request_deadline_seconds'],scope='REQUEST'):response=api.get_xdxr_info(target['market'],code.split('.')[0])
    summary=validate_response(code,response)
   except Exception as e:error={'type':type(e).__name__,'repr':repr(e),'chain':owner._exception_chain(e),'protocol_details':owner._protocol_response_details(e)};summary={}
   response_repr=None
   try:json.dumps(response,allow_nan=False)
   except (ValueError,TypeError) as e:
    response_repr=repr(response);response=None;error={'type':'NONFINITE_OR_UNSERIALIZABLE_PARSED_SOURCE','repr':repr(e)};summary={}
   p=out/'responses'/(code+'.json');save(p,{'code':code,'request':{'method':'get_xdxr_info','market':target['market'],'numeric_code':code.split('.')[0]},'observed_at':observed,'response_rows':response,'response_repr_if_not_JSON_representable':response_repr,'response_error':error,'capture_kind':'ORIGINAL_INSTALLED_TDX_PARSED_RESPONSE_NOT_WIRE','historical_available_asof_D22':None});results.append({'code':code,'market':target['market'],'status':'CAPTURED_COMPLETE_RESPONSE' if error is None else 'FAILED_NOT_NO_EVENTS','source_path':str(p),'source_sha256':sha(p),'response_format':'response_rows','requests_this_execution':1,'error':error,**summary})
   if error is not None:stop='FIRST_MARKET_METADATA_FAILURE_STOP_NO_BLIND_RETRY';checkpoint('FAILURE_'+str(calls));break
   if index+1==len(c['capability_control_codes']):checkpoint('THREE_MARKET_CONTROLS_PASSED')
   if calls==25:checkpoint('FIRST_25_THROUGHPUT')
   elif calls%100==0:checkpoint('BATCH_'+str(calls).zfill(6))
   if calls%c['session_chunk_size']==0:owner._disconnect_session(api);api=None
 finally:
  if api is not None:owner._disconnect_session(api)
 requested={r['code'] for r in results};remaining=[r['code'] for r in targets if r['code'] not in requested];result={'schema':'CANONICAL_SAME_OWNER_CURRENT_XDXR_REFRESH_V1','execution_id':c['execution_id'],'verified_start':gate,'results':results,'target_count':len(targets),'complete_success_count':sum(r['status']!='FAILED_NOT_NO_EVENTS' for r in results),'failed_count':sum(r['status']=='FAILED_NOT_NO_EVENTS' for r in results),'actual_requests':calls,'reused_captures':len(reuses),'unrequested_codes':remaining,'stop_reason':stop,'elapsed_seconds':time.monotonic()-started,'price_cutoff':'20261022','future_event_metadata_never_applied':True,'old_cache_replaced':False,'source_writes':0,'data_recovered':0,'bars_requests':0,'Futu_calls':0,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};save(out/'EVENT_REFRESH_RECEIPT.json',result);s=register(cp,'TERMINAL','XDXR58_EVENT_REFRESH_TERMINAL',[out/'EVENT_REFRESH_RECEIPT.json'],{'target_count':len(targets),'success':result['complete_success_count'],'requests':calls,'failed':result['failed_count'],'unrequested':len(remaining),'elapsed_seconds':result['elapsed_seconds']},'CURRENT_EVENT_SOURCES_CAPTURED_COMPLETE_NOT_INPUT_PROMOTED' if not remaining and not result['failed_count'] else 'PARTIAL_CURRENT_EVENT_CAPTURE_EXACT_REMAINDER_NOT_ZERO_EVENTS');save(out/'EXECUTION_TERMINAL_RECEIPT.json',s);print(json.dumps({k:result[k] for k in ['target_count','complete_success_count','failed_count','actual_requests','reused_captures','stop_reason','elapsed_seconds']},ensure_ascii=False),flush=True);return 0 if not remaining and not result['failed_count'] else 2
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
