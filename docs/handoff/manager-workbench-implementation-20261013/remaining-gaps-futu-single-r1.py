"""Authorized HK00068 single only. Existing Futu profile; no formal state or batch."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,logging.handlers,math,sys
HERE=Path(__file__).resolve().parent
OUT=HERE/'remaining-gaps-futu-single-r1'
sha=lambda b:hashlib.sha256(b).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def clean(v):
 if isinstance(v,float) and not math.isfinite(v):return None
 if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
 if isinstance(v,list):return [clean(x) for x in v]
 return v
if __name__=='__main__':
 sys.dont_write_bytecode=True
 if OUT.exists():raise ValueError('IMMUTABLE_SINGLE_OUTPUT_EXISTS_USE_SAVED_RESPONSE')
 OUT.mkdir();handler=logging.handlers.TimedRotatingFileHandler
 # SDK log routing is limited to this process, avoiding global Futu log writes.
 logging.handlers.TimedRotatingFileHandler=lambda filename,*a,**kw:handler(str(OUT/'sdk.log'),*a,**kw)
 try:
  from futu import OpenQuoteContext,RET_OK,KLType,AuType
 finally:logging.handlers.TimedRotatingFileHandler=handler
 request=dict(start='2026-07-17',end='2026-10-12',ktype='K_DAY',autype='NONE',max_count=1000)
 receipt=dict(source='FUTU',code='HK.00068',request=request,started_at=now(),shared_writes=0,formal_writes=0,model_calls=0,maximum_new_codes=1,authorization='User HK00068 single first; total new code ceiling94 includes single')
 ctx=OpenQuoteContext(host='127.0.0.1',port=11111)
 try:
  ret,quota=ctx.get_history_kl_quota(False)
  receipt['quota_before']=dict(ret=int(ret),used=int(quota[0]),remain=int(quota[1])) if ret==RET_OK else dict(ret=int(ret),error=str(quota))
  if ret!=RET_OK or int(quota[1])<1:raise ValueError('FUTU_QUOTA_UNAVAILABLE_NO_HISTORY_REQUEST')
  ret,frame,next_page=ctx.request_history_kline('HK.00068',start=request['start'],end=request['end'],ktype=KLType.K_DAY,autype=AuType.NONE,max_count=1000)
  receipt.update(return_code=int(ret),has_next_page=next_page is not None)
  if ret!=RET_OK:raise ValueError('FUTU_HISTORY_REJECTED:'+str(frame))
  rows=clean(frame.to_dict(orient='records'));raw=(json.dumps(rows,ensure_ascii=False,allow_nan=False)+'\n').encode();(OUT/'raw.json').write_bytes(raw)
  sessions=json.loads((HERE/'remaining-gaps-classification-r1.json').read_bytes())['requested_sessions'];dates=[v['time_key'][:10].replace('-','') for v in rows]
  receipt.update(raw_sha256=sha(raw),row_count=len(rows),columns=list(frame.columns),missing_sessions=sorted(set(sessions)-set(dates)),extra_sessions=sorted(set(dates)-set(sessions)),dates_equal_exact61=dates==sessions)
  # Full raw preserves every original row/price; nothing is clamped or filled.
  anomalies=[]
  for v in rows:
   if v['high']<max(v['open'],v['close'],v['low']) or v['low']>min(v['open'],v['close'],v['high']):anomalies.append(v['time_key'])
  receipt['ohlc_anomaly_dates']=anomalies
  qr,q=ctx.get_history_kl_quota(False);receipt['quota_after']=dict(ret=int(qr),used=int(q[0]),remain=int(q[1])) if qr==RET_OK else dict(ret=int(qr),error=str(q))
  receipt['status']='CAPTURED_COMPLETE' if dates==sessions and len(rows)==61 and next_page is None and not anomalies else 'CAPTURED_UNASSESSED'
 except Exception as e:receipt.update(status='CANNOT_CONFIRM',error_type=type(e).__name__,error=str(e))
 finally:ctx.close();receipt['finished_at']=now();(OUT/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(receipt=str(OUT/'receipt.json'),sha256=sha((OUT/'receipt.json').read_bytes()),status=receipt['status']),ensure_ascii=False))
