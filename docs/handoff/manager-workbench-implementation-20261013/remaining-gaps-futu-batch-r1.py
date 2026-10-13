"""Reviewed-plan wrapper for existing Futu daily-history evidence. No formal state."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import argparse,fcntl,hashlib,json,logging.handlers,math,sys,time
HERE=Path(__file__).resolve().parent
PLAN_SHA='e4d29a9e62f4a26741106c28b8762cf3d7c01b219a1e1c36b06652cb474de9f0'
RATE_LIMIT_ERROR='FUTU_HISTORY_SOURCE_REJECTED:获取历史K线频率太高，请求失败，每30秒最多60次。'
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def save(path,value):
 with path.open('x') as f:f.write(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def clean(v):
 if isinstance(v,float) and not math.isfinite(v):return None
 if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
 if isinstance(v,list):return [clean(x) for x in v]
 return v

class HistoryThrottle:
 def __init__(self,clock=time.monotonic,sleep=time.sleep):self.clock=clock;self.sleep=sleep;self.last=None
 def wait(self):
  # One sequential owner: 60 requests span >=30.09s, not a 60-call burst.
  if self.last is not None:
   delay=0.51-(self.clock()-self.last)
   if delay>0:self.sleep(delay)
  self.last=self.clock()

def rate_limit_recovery(root,code,request,at=None):
 raw=(root/'receipt.json').read_bytes();r=json.loads(raw)
 if (r.get('source')!='FUTU' or r.get('code')!=code or r.get('request')!=request
     or r.get('status')!='UNASSESSED' or r.get('error')!=RATE_LIMIT_ERROR):return None,None,'SAVED_FAILED_ATTEMPT_NO_BLIND_RETRY'
 finished=datetime.fromisoformat(r['finished_at'])
 if finished.utcoffset() is None or (at or datetime.now(timezone.utc))<finished+timedelta(seconds=30):return None,None,'RATE_LIMIT_WINDOW_NOT_ELAPSED'
 attempt=root/'attempts/rate-limit-recovery-r1'
 if attempt.exists():return None,None,'RATE_LIMIT_RECOVERY_ALREADY_ATTEMPTED'
 return attempt,dict(path=str(root/'receipt.json'),sha256=sha(raw),error=RATE_LIMIT_ERROR,finished_at=r['finished_at']),'RATE_LIMIT_RECOVERY_ALLOWED'

def validate_cached(binding,code,request,sessions):
 root=Path(binding['source_local_path']);raw=(root/binding['raw_relative']).read_bytes();receipt_raw=(root/binding['receipt_relative']).read_bytes();receipt=json.loads(receipt_raw)
 if sha(raw)!=binding['raw_sha256'] or sha(receipt_raw)!=binding['receipt_sha256']:raise ValueError('FUTU_IMMUTABLE_SOURCE_DRIFT')
 start=datetime.fromisoformat(receipt['started_at']);end=datetime.fromisoformat(receipt['finished_at'])
 if start.utcoffset() is None or end.utcoffset() is None or not start<=end<=datetime.now(timezone.utc):raise ValueError('FUTU_REQUEST_TIME_INVALID')
 rows=json.loads(raw)
 if (binding['symbol']!=code or receipt.get('source')!='FUTU' or receipt.get('code')!=code or receipt.get('request')!=request
     or receipt.get('return_code')!=0 or receipt.get('has_next_page') is not False or receipt.get('raw_sha256')!=sha(raw)
     or receipt.get('row_count')!=61 or receipt.get('missing_sessions')!=[] or receipt.get('extra_sessions')!=[]
     or len(rows)!=61 or [r['time_key'][:10].replace('-','') for r in rows]!=sessions or any(r.get('code')!=code for r in rows)):
  raise ValueError('FUTU_EXACT_PROFILE_OR_61_INVALID')
 for r in rows:
  v=[r.get(k) for k in ('open','high','low','close','volume')]
  if any(x is None or not math.isfinite(float(x)) for x in v) or min(v[:4])<=0 or v[4]<0 or v[1]<max(v[:4]) or v[2]>min(v[:4]):raise ValueError('FUTU_OHLC_OR_VOLUME_INVALID')
 return binding

def fetch_one(ctx,code,request,root,sessions,ktype,autype,*,throttle=None,prior_attempt=None):
 root.mkdir();r=dict(source='FUTU',code=code,request=request,started_at=now(),formal_writes=0,model_calls=0,shared_writes=0)
 if prior_attempt:r['prior_failed_attempt']=prior_attempt
 binding=None
 try:
  ret,q=ctx.get_history_kl_quota(False);r['quota_before']=dict(ret=int(ret),used=int(q[0]),remain=int(q[1])) if ret==0 else dict(ret=int(ret),error=str(q))
  if ret!=0 or int(q[1])<1:raise ValueError('FUTU_QUOTA_STOP_ZERO_REQUESTS')
  if throttle:throttle()
  r['history_requested_at']=now()
  ret,frame,next_page=ctx.request_history_kline(code,start=request['start'],end=request['end'],ktype=ktype,autype=autype,max_count=request['max_count'])
  r.update(return_code=int(ret),has_next_page=next_page is not None)
  if ret!=0:raise ValueError('FUTU_HISTORY_SOURCE_REJECTED:'+str(frame))
  rows=clean(frame.to_dict(orient='records'));raw=(json.dumps(rows,ensure_ascii=False,allow_nan=False)+'\n').encode()
  with (root/'raw.json').open('xb') as f:f.write(raw)
  dates=[v['time_key'][:10].replace('-','') for v in rows]
  r.update(raw_sha256=sha(raw),row_count=len(rows),missing_sessions=sorted(set(sessions)-set(dates)),extra_sessions=sorted(set(dates)-set(sessions)))
  qr,q=ctx.get_history_kl_quota(False);r['quota_after']=dict(ret=int(qr),used=int(q[0]),remain=int(q[1])) if qr==0 else dict(ret=int(qr),error=str(q))
  r['status']='CAPTURED'
 except Exception as e:r.update(status='UNASSESSED',error_type=type(e).__name__,error=str(e))
 r['finished_at']=now();save(root/'receipt.json',r)
 if r['status']=='CAPTURED':
  binding=dict(source_local_path=str(root),symbol=code,raw_relative='raw.json',raw_sha256=sha((root/'raw.json').read_bytes()),receipt_relative='receipt.json',receipt_sha256=sha((root/'receipt.json').read_bytes()))
  try:validate_cached(binding,code,request,sessions)
  except Exception as e:return None,dict(code=code,status='UNASSESSED',error=str(e),preserved_receipt=str(root/'receipt.json'))
  save(root/'binding.json',binding)
 return binding,dict(code=code,status='READY' if binding else 'UNASSESSED',receipt=str(root/'receipt.json'),error=r.get('error'))

def load_plan(path):
 raw=path.read_bytes()
 if sha(raw)!=PLAN_SHA:raise ValueError('FIXED94_PLAN_DRIFT')
 p=json.loads(raw);codes=p['ordered_codes'];d=json.loads((HERE/'remaining-gaps-classification-r1.json').read_bytes())
 if sha((HERE/'remaining-gaps-classification-r1.json').read_bytes())!=p['classification_sha256']:raise ValueError('CLASSIFICATION_DRIFT')
 eligible={c['code'] for c in d['codes'] if c['category']=='OHLC_ONLY'}
 if len(codes)!=94 or len(set(codes))!=94 or codes[0]!='HK.00068' or not set(codes).issubset(eligible) or p['total_code_ceiling']!=94:raise ValueError('EXACT94_CODE_SCOPE_INVALID')
 validate_cached(p['canary_binding'],'HK.00068',p['request'],d['requested_sessions'])
 return p,d['requested_sessions']

def main():
 sys.dont_write_bytecode=True
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,default=HERE/'remaining-gaps-futu-plan-r1.json');p.add_argument('--output',type=Path,required=True);p.add_argument('--execute',action='store_true');a=p.parse_args();plan,sessions=load_plan(a.plan);out=a.output.resolve()
 if out.parent!=HERE or not out.name.startswith('remaining-gaps-'):raise ValueError('HANDOFF_DIAGNOSTIC_ONLY')
 if not a.execute:print(json.dumps(dict(status='PREPARED_NO_NETWORK',code_count=94,canary_cache_validated=True,additional_requests_max=93)));return
 out.mkdir(exist_ok=True);ctx=None;bindings=[];results=[];throttle=HistoryThrottle()
 with (out/'owner.lock').open('a') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:
   for code in plan['ordered_codes']:
    root=out/code;binding=None;request_root=root;prior_attempt=None
    if code=='HK.00068':binding=plan['canary_binding']
    elif (root/'binding.json').exists():binding=json.loads((root/'binding.json').read_bytes())
    elif (root/'receipt.json').exists():
     request_root,prior_attempt,reason=rate_limit_recovery(root,code,plan['request'])
     if request_root is None:results.append(dict(code=code,status='UNASSESSED',reason=reason));continue
    elif root.exists():raise ValueError('INCOMPLETE_ATTEMPT_REQUIRES_REVIEW:'+code)
    if binding is None:
     if ctx is None:
      handler=logging.handlers.TimedRotatingFileHandler
      logging.handlers.TimedRotatingFileHandler=lambda name,*args,**kw:handler(str(out/'sdk.log'),*args,**kw)
      try:from futu import OpenQuoteContext,KLType,AuType
      finally:logging.handlers.TimedRotatingFileHandler=handler
      ctx=OpenQuoteContext(host='127.0.0.1',port=11111)
     request_root.parent.mkdir(parents=True,exist_ok=True)
     binding,result=fetch_one(ctx,code,plan['request'],request_root,sessions,KLType.K_DAY,AuType.NONE,throttle=throttle.wait,prior_attempt=prior_attempt);results.append(result)
     if not binding:
      if result.get('error')=='FUTU_QUOTA_STOP_ZERO_REQUESTS':break
      continue
     if prior_attempt:save(root/'binding.json',binding)
    validate_cached(binding,code,plan['request'],sessions);bindings.append(binding)
    if not any(r['code']==code for r in results):results.append(dict(code=code,status='READY',cache_hit=True))
    print(json.dumps(dict(processed=len(results),code=code,ready=len(bindings))),flush=True)
  finally:
   if ctx:ctx.close()
   # A new immutable progress product per invocation; original responses remain.
   report=dict(status='CAPTURE_COMPLETE_OR_EXPLICIT_GAPS',bindings=bindings,results=results,planned_count=94,unprocessed_codes=[c for c in plan['ordered_codes'] if c not in {r['code'] for r in results}],excluded_codes=plan['remaining_codes'],mother_scope_count=692,formal_writes=0,model_calls=0,completed_at=now())
   product=out/('binding-product-'+sha(json.dumps(report,sort_keys=True).encode())[:24]+'.json');save(product,report);print(json.dumps(dict(product=str(product),sha256=sha(product.read_bytes()),ready=len(bindings))),flush=True)
if __name__=='__main__':main()
