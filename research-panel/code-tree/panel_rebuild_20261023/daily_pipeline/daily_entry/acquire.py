"""Acquire official daily G4 and changed GBBQ into isolated research storage.
No full-history download, publication, policy changes, code download, fit or upload.
"""
import argparse, collections, datetime, fcntl, hashlib, importlib.util, io, json, re, urllib.error, urllib.request, zipfile, uuid
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo
HERE=Path(__file__).resolve().parent

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
P=module('acquisition_pipeline',HERE.parent/'pipeline_v4.py')
PROBE=module('acquisition_probe',HERE/'source_probe.py')
RECOVERY=P.PROJECT.parent/'panel_input_recovery_20261023'
MAX_BYTES=32*1024*1024

def full_scope(manifest):
 return sorted({r['symbol'] for r in manifest['securities'] if re.fullmatch(r'\d{6}\.(SH|SZ)',r['symbol'])})

def changed_symbols(old,new):
 def group(events):
  d=collections.defaultdict(list)
  for e in events:
   if e['market'] in (0,1):d[e['code']+('.SZ' if e['market']==0 else '.SH')].append({k:v for k,v in e.items() if k!='record_index'})
  return {k:sorted(P.canonical(x) for x in v) for k,v in d.items()}
 a,b=group(old),group(new)
 return sorted(k for k in a.keys()|b.keys() if a.get(k)!=b.get(k))

def inspect_zip(data,limit=64*1024*1024):
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  names=z.namelist()
  if len(names)!=len(set(names)):raise ValueError('DUPLICATE_ZIP_MEMBER')
  if any(PurePosixPath(n.replace('\\','/')).is_absolute() or '..' in PurePosixPath(n.replace('\\','/')).parts for n in names):raise ValueError('UNSAFE_ZIP_PATH')
  if sum(i.file_size for i in z.infolist())>limit:raise ValueError('ZIP_EXPANDED_SIZE_LIMIT')
  if z.testzip() is not None:raise ValueError('ZIP_CRC_FAILURE')
  return names

def pin(path):return {'path':str(path),'sha256':P.sha(path)}
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def cached_record(path,url,headers,expected_sha):
 if P.sha(path)!=expected_sha:raise ValueError('CACHED_SOURCE_HASH_CHANGED')
 return {'path':str(path),'url':url,'headers':headers,'sha256':expected_sha,'bytes':path.stat().st_size,'downloaded':False}

def acquire_url(url,storage,prior=None):
 # Fixed official URL allowlist; no cross-host redirects or full-history source.
 if not (url=='https://www.tdx.com.cn/products/data/data/dbf/gbbq.zip' or re.fullmatch(r'https://www\.tdx\.com\.cn/products/data/data/g4day/\d{8}\.zip',url)):
  raise ValueError('SOURCE_URL_NOT_ALLOWED')
 if prior and prior.get('url')!=url:raise ValueError('PRIOR_SOURCE_URL_MISMATCH')
 opener=urllib.request.build_opener(PROBE.NoRedirect())
 observed=now();headers=PROBE.conditionals(prior.get('headers',{})) if prior else {}
 try:
  with opener.open(urllib.request.Request(url,method='HEAD',headers=headers),timeout=20) as r:status=r.status;meta=dict(r.headers)
 except urllib.error.HTTPError as e:
  if e.code!=304 or not prior:raise
  cached=cached_record(P.safe_ancestors(prior['path']),url,prior['headers'],prior['sha256'])
  return cached|{'observed_at_utc':observed,'http_status':304,'observation':'CONDITIONAL_UNCHANGED_NOT_PIT'}
 length=int(meta.get('Content-Length',meta.get('content-length','0')))
 if not 0<length<=MAX_BYTES:raise ValueError('SOURCE_LENGTH_MISSING_OR_LIMIT')
 request_headers={}
 etag=meta.get('ETag',meta.get('etag'))
 if not etag or etag.startswith('W/'):raise ValueError('STRONG_ETAG_REQUIRED_FOR_GET')
 request_headers['If-Match']=etag
 with opener.open(urllib.request.Request(url,headers=request_headers),timeout=30) as r:
  if r.status!=200:raise ValueError('SOURCE_GET_NOT_200')
  body=r.read(MAX_BYTES+1);get_headers=dict(r.headers)
 if etag and get_headers.get('ETag',get_headers.get('etag'))!=etag:raise ValueError('SOURCE_ETAG_CHANGED_BETWEEN_HEAD_GET')
 if len(body)!=length or len(body)>MAX_BYTES:raise ValueError('SOURCE_LENGTH_CHANGED_OR_LIMIT')
 inspect_zip(body)
 digest=hashlib.sha256(body).hexdigest();path=storage/(digest+'.zip')
 if path.exists():
  if P.sha(path)!=digest:raise ValueError('CONTENT_STORE_CORRUPTION')
 else:P.atomic(path,body)
 return {'path':str(path),'url':url,'headers':get_headers,'head_headers':meta,'sha256':digest,'bytes':len(body),'downloaded':True,'observed_at_utc':observed,'http_status':200,'known_at_status':'FIRST_OBSERVED_NOW_NOT_HISTORICAL_KNOWN_AT'}

def cached_events(data,archive_sha,storage,engine,constants,decoder_sha):
 binding={'archive_sha256':archive_sha,'decoder_sha256':decoder_sha,'constants_sha256':P.sha(constants)}
 key=hashlib.sha256(P.canonical(binding)).hexdigest()
 path=storage/(key+'.events.json');receipt=storage/(key+'.decode.json')
 if receipt.exists():
  saved=P.load(receipt)
  if saved.get('binding')!=binding or not path.is_file() or P.sha(path)!=saved.get('events_sha256'):raise ValueError('DECODED_CACHE_BINDING_OR_SHA')
  return path,P.load(path),True
 if path.exists():raise ValueError('DECODED_CACHE_ORPHAN_REQUIRES_REVIEW')
 with zipfile.ZipFile(io.BytesIO(data)) as z:events=engine.decode_gbbq(z.read('gbbq'),constants.read_bytes())
 P.save(path,events);P.save(receipt,{'binding':binding,'events_sha256':P.sha(path)})
 return path,events,False

def run(date,base_config,replay=False):
 P.date_ok(date);base=P.load(P.safe_ancestors(base_config));prepared=P.prepare(base)
 gate=P.calendar_gate(prepared[6],date)
 if gate['status']=='MARKET_CLOSED_NO_UPDATE':return {'status':'MARKET_CLOSED_NO_UPDATE','target_date':date}
 if not gate['publish_allowed']:raise ValueError(gate['status'])
 if date<prepared[2]['source_vintage']:raise ValueError('TARGET_BEFORE_BASELINE')
 root=P.safe_output(HERE/'acquired');root.mkdir(exist_ok=True)
 with (root/'ACQUIRE.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  storage=root/'objects';storage.mkdir(exist_ok=True)
  g4url=f'https://www.tdx.com.cn/products/data/data/g4day/{date}.zip'
  local=P.PROJECT/'daily_update'/f'g4day_{date}.zip'
  g4receipt=P.PROJECT/'daily_update/DAILY_G4_SOURCE_RECEIPT.json'
  if date=='20261023' and local.exists():
   r=P.load(g4receipt)
   if r['url']!=g4url:raise ValueError('G4_LOCAL_PROVENANCE')
   daily=cached_record(local,g4url,{},r['sha256'])|{'observation':'HISTORICAL_LOCAL_REPLAY','observed_at_utc':now()}
  elif replay:raise ValueError('REPLAY_REQUIRES_EXISTING_VERIFIED_SOURCE')
  else:
   previous=root/date/'ACQUISITION.json'
   prior=P.load(previous)['daily'] if previous.exists() else None
   daily=acquire_url(g4url,storage,prior)
  inspect_zip(Path(daily['path']).read_bytes())
  original=P.load(RECOVERY/'GBBQ_DOWNLOAD_RECEIPT.json')
  original_source=cached_record(RECOVERY/'gbbq_20261023.zip',original['url'],original['headers'],original['sha256'])
  state=root/'GBBQ_SOURCE_STATE.json';prior=P.load(state) if state.exists() else original_source
  rights=original_source|{'observation':'HISTORICAL_LOCAL_REPLAY','observed_at_utc':now()} if replay else acquire_url(original['url'],storage,prior)
  data=Path(rights['path']).read_bytes();names=inspect_zip(data)
  if 'gbbq' not in names:raise ValueError('GBBQ_MEMBER_MISSING')
  old=P.load(prepared[1]['baseline_events'])
  decoded_cache_reused=False
  if rights['sha256']==original['sha256']:
   # Exact original archive matches original reviewed decoded bytes; never relabel known_at.
   events_path=P.PROJECT/'data/events_decoded.json'
   if P.sha(events_path)!='a0be041aeb621cba525bce71141da211d5c67428e5f288aeaaf043ee15718431':raise ValueError('ORIGINAL_DECODED_EVENTS_CHANGED')
   events=P.load(events_path)
  else:
   constants=P.PROJECT/'data/gbbq_public_format_constants.bin'
   if P.sha(constants)!='2cdbe88a76fd70bdb3338d1cf5e2400e16412994c8cf5e1eafbefe2dcabd2e45':raise ValueError('CONSTANTS_HASH_CHANGED')
   engine=P.engines()[0]
   events_path,events,decoded_cache_reused=cached_events(data,rights['sha256'],storage,engine,constants,P.sha(P.PROJECT/'data/data_engine.py'))
  changes=changed_symbols(old,events)
  symbols=full_scope(prepared[2]);snapshot=P.g4_snapshot(daily['path'],date,symbols,P.engines()[2])
  missing=sorted(set(symbols)-snapshot.keys());errors={s:r['error'] for s,r in snapshot.items() if 'error' in r}
  folder=root/date;folder.mkdir(exist_ok=True)
  source={'date':date,'daily_sha256':daily['sha256'],'events_sha256':P.sha(events_path),'daily_source_url':g4url,'events_source_url':rights['url'],'rights_archive_sha256':rights['sha256'],'PIT':False,'known_at_status':'OBSERVATION_ONLY_NOT_HISTORICAL_KNOWN_AT'}
  # Actual observations remain append-only and never enter the market run identity.
  observation_id=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+uuid.uuid4().hex
  P.save(folder/'observations'/(observation_id+'.json'),{'daily':daily,'rights':rights,'observed_at_utc':now(),'replay':replay,'decoded_cache_reused':decoded_cache_reused})
  P.save(folder/'SOURCE_RECEIPT.json',source)
  config=dict(base);config.pop('release',None);config.pop('event_reviews',None)
  config.update(date=date,vintage=date,g4_trade_date=date,events_vintage=date,symbols=symbols,daily=pin(Path(daily['path'])),events=pin(events_path),source_receipt=pin(folder/'SOURCE_RECEIPT.json'))
  P.save(folder/'CANDIDATE_CONFIG.json',config)
  receipt={'status':'ACQUIRED_CANDIDATE_NOT_RELEASED','target_date':date,'replay':replay,'decoded_cache_reused':decoded_cache_reused,'daily':daily,'rights':rights,'scope_count':len(symbols),'scope_basis':'ALL_SH_SZ_BASELINE_SYMBOLS_INCLUDING_QUARANTINED_NOT_ALL_A_CERTIFICATION','g4_present_count':len(snapshot),'g4_missing_symbols':missing,'g4_invalid_symbols':errors,'changed_event_symbols_requiring_review':changes,'candidate_config':str(folder/'CANDIDATE_CONFIG.json'),'blockers':['INDEPENDENT_CONFIG_AND_SNAPSHOT_REVIEW_REQUIRED','EXTRAORDINARY_CALENDAR_REFRESH_REQUIRED']+(['CORPORATE_ACTION_CHANGES_REQUIRE_PER_SYMBOL_REVIEW'] if changes else [])+(['G4_SCOPE_INCOMPLETE_OR_INVALID'] if missing or errors else []),'natural_scheduled_run':'NOT_RUN','PIT':False,'published':False,'uploaded':False}
  P.save(folder/'ACQUISITION.json',receipt)
  if not replay:P.save(state,rights)
  return receipt

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--date');a.add_argument('--base-config',default=str(HERE.parent/'REAL_CONFIG_V4.json'));a.add_argument('--replay-existing',action='store_true');args=a.parse_args()
 try:
  r=run(args.date or datetime.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'),args.base_config,args.replay_existing);print(json.dumps(r,ensure_ascii=False,indent=2));return 0
 except Exception as e:print(json.dumps({'status':'ACQUISITION_BLOCKED','error':type(e).__name__+': '+str(e),'published':False}));return 2
if __name__=='__main__':raise SystemExit(main())
