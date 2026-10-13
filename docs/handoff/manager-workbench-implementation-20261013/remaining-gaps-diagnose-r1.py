"""Read-only saved TDX diagnosis; bounded two representative queries only on canary."""
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import argparse,hashlib,json,struct,sys,zipfile
HERE=Path(__file__).resolve().parent
OWNER=HERE/'.tmp/tdxpy61-owner-r1'
RUN=OWNER/'runs/20261012/d4c85f8da7fd6e36cce325ae'
RAW_SHA='d4c85f8da7fd6e36cce325ae5d04222a7c8bb3e0bc05031c30db6efb713486e5'
MANIFEST_SHA='5d111e392708a040d3e9b67b32301d966e8e80643bc1cf168e88963d5ffba294'
WHEEL=HERE/'.tmp/tdxpy-official-source/tdxpy-0.2.7.whl'
WHEEL_SHA='5514d35608fac2c7b2acf693de6f41ba7ccda58207b65a3f374c89887560737c'
PARSER='tdxpy/parser/ext/ex_get_instrument_bars.py'
PARSER_SHA='263abf7d5c63e836bddb6ffb35f7d7150d4a33b7d4ac96eefd49d8a8d64a99ad'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def load():
 raw=(RUN/'raw_capture.json').read_bytes();manifest=(RUN/'manifest.json').read_bytes()
 if sha(raw)!=RAW_SHA or sha(manifest)!=MANIFEST_SHA:raise ValueError('FROZEN_INPUT_DRIFT')
 return json.loads(raw)
def analyze(rows,sessions):
 wanted=set(sessions);dates=[r['datetime'][:10].replace('-','') for r in rows];bad=[]
 for r,d in zip(rows,dates):
  if d not in wanted:continue
  fields={k:r[k] for k in ('open','high','low','close')};violations=[]
  for k in ('open','close'):
   for comparison,limit in [('ABOVE_HIGH','high'),('BELOW_LOW','low')]:
    delta=fields[k]-fields[limit] if comparison=='ABOVE_HIGH' else fields[limit]-fields[k]
    if delta>0:
     bits=lambda v:struct.unpack('<I',struct.pack('<f',v))[0]
     violations.append(dict(field=k,type=comparison,absolute_delta=delta,float32_ulp_distance=abs(bits(fields[k])-bits(fields[limit]))))
  if fields['high']<fields['low']:violations.append(dict(type='HIGH_BELOW_LOW'))
  if violations:bad.append(dict(trade_date=d,fields=fields,violations=violations))
 return dict(missing_sessions=sorted(wanted-set(dates)),duplicate_sessions=sorted(k for k,v in Counter(dates).items() if v>1),ohlc_anomalies=bad,returned_rows=len(rows),returned_first_date=min(dates) if dates else None,returned_last_date=max(dates) if dates else None)
def diagnose(output):
 if output.exists() or output.parent!=HERE or not output.name.startswith('remaining-gaps-'):raise ValueError('NEW_DIAGNOSTIC_ONLY')
 raw=load();unknown={r['code'] for r in raw['records'] if r['status']!='READY'};attempts=defaultdict(list);counts=Counter()
 for a in raw['failed_attempts']:
  if sha(canonical(a['source_rows']))!=a['response_sha256'] or sha(canonical(a['request']))!=a['request_sha256']:raise ValueError('ATTEMPT_SHA_INVALID')
  analysis=analyze(a['source_rows'],raw['requested_sessions'])
  attempts[a['code']].append(dict(endpoint=a['endpoint'],request_sha256=a['request_sha256'],response_sha256=a['response_sha256'],primary_error=a['error'],**analysis))
 codes=[]
 for code in sorted(unknown):
  values=attempts[code];bad=any(a['ohlc_anomalies'] for a in values);missing=any(a['missing_sessions'] for a in values)
  category='OHLC_AND_MISSING_SESSION' if bad and missing else 'OHLC_ONLY' if bad else 'MISSING_SESSION_ONLY' if missing else 'OTHER'
  counts[category]+=1;codes.append(dict(code=code,category=category,attempts=values,status='UNASSESSED',listing_or_suspension_evidence='CANNOT_CONFIRM'))
 cached=[]
 for p in sorted((OWNER/'cache').glob('*.json')):
  r=json.loads(p.read_bytes())
  if r.get('code') not in unknown:continue
  checks=analyze(r.get('source_rows',[]),raw['requested_sessions'])
  cached.append(dict(path=str(p),raw_sha256=sha(p.read_bytes()),code=r['code'],profile_matches=all(r.get('request',{}).get(k)==v for k,v in raw['profile'].items()),**checks))
 with zipfile.ZipFile(WHEEL) as z:
  if sha(WHEEL.read_bytes())!=WHEEL_SHA or sha(z.read(PARSER))!=PARSER_SHA:raise ValueError('OFFICIAL_PARSER_DRIFT')
 primary=Counter(','.join(sorted({a['primary_error'] for a in c['attempts']})) for c in codes)
 result=dict(status='DIAGNOSED_NOT_REPAIRED',input_raw_sha256=RAW_SHA,input_manifest_sha256=MANIFEST_SHA,scope_count=692,ready_count=568,unassessed_count=len(unknown),categories=dict(counts),primary_error_categories=dict(primary),codes=codes,same_owner_cached_unknown_records=cached,parser=dict(wheel_sha256=WHEEL_SHA,parser_sha256=PARSER_SHA,decode='direct IEEE754 float32 <ffffIIf; no price scaling/rounding in official parseResponse'),requested_sessions=raw['requested_sessions'],panel_identity=raw['panel_identity'],panel_window_status='Prior independently verified panel-valid0/gaps692; unit/basis not proven; no historic source substitution',historical_versions_modified=False,network_calls=0,formal_writes=0,rule_changes=0)
 output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(output=str(output),sha256=sha(output.read_bytes()),counts=result['categories'],cached_unknown_records=len(cached))))
def canary(output):
 if output.exists() or output.parent!=HERE or not output.name.startswith('remaining-gaps-'):raise ValueError('NEW_DIAGNOSTIC_ONLY')
 original=load();sdk=OWNER/'sdk'
 # All loaded SDK Python bytes must match the existing official wheel.
 with zipfile.ZipFile(WHEEL) as z:
  if sha(WHEEL.read_bytes())!=WHEEL_SHA:raise ValueError('WHEEL_DRIFT')
  for n in z.namelist():
   if n.startswith('tdxpy/') and n.endswith('.py'):
    if (sdk/n).read_bytes()!=z.read(n):raise ValueError('SDK_DRIFT:'+n)
 sys.dont_write_bytecode=True;sys.path.insert(0,str(sdk))
 from tdxpy.exhq import TdxExHq_API
 from tdxpy.parser.ext.ex_get_instrument_bars import GetInstrumentBars
 from tdxpy.helper import get_datetime
 if sha((sdk/PARSER).read_bytes())!=PARSER_SHA:raise ValueError('PARSER_DRIFT')
 output.mkdir();results=[];parse=GetInstrumentBars.parseResponse;captured=[]
 def observe(self,buf):
  captured.append(bytes(buf));return parse(self,buf)
 GetInstrumentBars.parseResponse=observe
 # Existing saved catalogue uniquely confirms identity and market31 for both.
 endpoint='116.205.143.214:7727'
 for code in ['HK.00068','HK.00187']:
  saved=next(a for a in original['failed_attempts'] if a['code']==code and a['endpoint']==endpoint)
  request=saved['request'];catalogue=next(c for c in original['catalogues'] if c['endpoint']==endpoint)
  identity=[r for r in catalogue['rows'] if r.get('code')==code[3:] and r.get('market') in [31,48,49]]
  if len(identity)!=1 or identity[0]['market']!=request['market']:raise ValueError('SECURITY_IDENTITY_INVALID')
  api=TdxExHq_API(heartbeat=False,auto_retry=False,raise_exception=True);start=datetime.now(timezone.utc).isoformat();captured.clear()
  record=dict(code=code,endpoint=endpoint,request=request,request_sha256=sha(canonical(request)),saved_response_sha256=saved['response_sha256'],started_at=start,security_identity=identity[0])
  try:
   host,port=endpoint.split(':')
   if not api.connect(host,int(port),time_out=2.0):raise ConnectionError('APPROVED_NODE_CONNECTION_FAILED')
   api.client.settimeout(2.0)
   rows=list(api.get_instrument_bars(4,request['market'],code[3:],0,128));record.update(response_sha256=sha(canonical(rows)),analysis=analyze(rows,original['requested_sessions']))
   (output/(code+'.response.json')).write_bytes(canonical(rows))
   if len(captured)!=1:raise ValueError('WIRE_CAPTURE_COUNT_INVALID')
   body=captured[0];(output/(code+'.wire.bin')).write_bytes(body);record['wire_sha256']=sha(body)
   pos=20;wire_rows=[]
   for i in range(struct.unpack('<H',body[18:20])[0]):
    y,m,d,hr,mn,pos=get_datetime(4,body,pos);values=struct.unpack('<ffffIIf',body[pos:pos+28]);pos+=28
    wire_rows.append(dict(date=f'{y:04}{m:02}{d:02}',float32_hex={k:struct.pack('<f',v).hex() for k,v in zip(['open','high','low','close'],values[:4])}))
   assert all(wire_rows[i]['float32_hex']=={k:struct.pack('<f',rows[i][k]).hex() for k in ['open','high','low','close']} for i in range(len(rows)))
   record.update(status='RECEIVED_STRICTLY_DIAGNOSED',wire_to_official_float32_exact=True,window_rows_same_as_saved=[r for r in rows if r['datetime'][:10].replace('-','') in original['requested_sessions']]==[r for r in saved['source_rows'] if r['datetime'][:10].replace('-','') in original['requested_sessions']],wire_window_evidence=[w for w in wire_rows if w['date'] in set(original['requested_sessions'])])
  except Exception as e:record.update(status='CANNOT_CONFIRM',error_type=type(e).__name__,error=str(e))
  finally:api.disconnect();record['finished_at']=datetime.now(timezone.utc).isoformat();results.append(record)
 GetInstrumentBars.parseResponse=parse
 result=dict(status='BOUNDED_DIAGNOSTIC_CANARY',representatives=results,max_bar_requests=2,actual_attempted_bar_requests=sum('response_sha256' in r for r in results),model_calls=0,futu_calls=0,formal_writes=0,business_changes=0,original_raw_sha256=RAW_SHA)
 (output/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(receipt=str(output/'receipt.json'),sha256=sha((output/'receipt.json').read_bytes()),statuses=[r['status'] for r in results])))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['diagnose','canary']);p.add_argument('--output',type=Path,required=True);a=p.parse_args();globals()[a.mode](a.output.resolve())
