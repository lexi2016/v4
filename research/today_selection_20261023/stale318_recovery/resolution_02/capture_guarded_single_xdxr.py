"""One explicit same-owner ex-rights request for an evidenced stale event-cache gap."""
import argparse,hashlib,json,os,sys
from pathlib import Path
from datetime import datetime,timezone
sys.dont_write_bytecode=True
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=json.loads(Path(cp).read_text());out=Path(c['output_directory']);b=c['input_identity'];requests=0
 def fence(event,args):
  if event.startswith(('sqlite3.connect','subprocess.Popen')):raise RuntimeError('NO_OTHER_IO')
  if event=='socket.connect':assert args[1]==(c['host'],c['port']),'HOST_NOT_FROZEN'
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):assert out.resolve() in Path(os.fsdecode(args[0])).resolve().parents,'OUTPUT_ONLY'
 sys.addaudithook(fence);sys.path.insert(0,b['owner_worktree']);from ops import a_share_daily_sync as owner
 assert owner.TdxHq_API is not None;api=owner._runtime_api_factory(c['host'],c['port']);response=None;error=None;connected=False;observed=None
 try:
  with owner._deadline_guard(c['connect_budget_seconds'],scope='CONNECT'):owner._connect_session(api,c['host'],c['port'],c['socket_timeout_seconds'])
  connected=True;observed=datetime.now(timezone.utc).isoformat();assert requests==0;requests+=1
  with owner._deadline_guard(c['request_deadline_seconds'],scope='REQUEST'):response=api.get_xdxr_info(c['market'],c['numeric_code'])
 except Exception as e:error={'type':type(e).__name__,'repr':repr(e),'exception_chain':owner._exception_chain(e),'protocol_details':owner._protocol_response_details(e)}
 finally:owner._disconnect_session(api)
 p=out/'XDXR_PARSED_RESPONSE.json';assert not p.exists();p.write_text(json.dumps({'code':c['financial_code'],'request':{'method':'get_xdxr_info','market':c['market'],'code':c['numeric_code']},'observed_at':observed,'response_rows':response,'response_error':error,'capture_kind':'ACTUAL_INSTALLED_TDX_PARSED_RESPONSE_NOT_RAW_TCP','verified_start':gate},ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 result={'schema':'SINGLE_GUARDED_TDX_XDXR_CACHE_GAP_CAPTURE_V1','execution_id':c['execution_id'],'connected':connected,'requests':requests,'auto_retries':0,'response_path':str(p),'response_sha256':sha(p),'response_rows':len(response) if isinstance(response,list) else None,'error':error,'event_interpretation':'PENDING_EXACT_EFFECTIVE_DATE_COMPARISON_NOT_PRICE_REPAIR','network_scope':'OriginalsameTDXhost/get_xdxr_infoonly; no bars/Futu/Windows','source_writes':0,'data_recovered':0,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};(out/'EVENT_CAPTURE_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False));return 0 if error is None and isinstance(response,list) else 2
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
